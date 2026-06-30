import os
import re
import sys
import json
import datetime
import asyncio
from typing import Any, Union, Optional

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.events import RequestInput
from google.adk import Context, Workflow
from google.adk.workflow import node, START
from mcp import StdioServerParameters
from google.adk.tools import McpToolset

from app.config import config

# Model initialization using the environment configuration
model_instance = Gemini(model=config.model)

# Bind robust retry wrappers to the model instance to intercept transient API errors (429, 503)
import types
import time
import asyncio

original_generate_content_async = model_instance.generate_content_async

async def wrapped_generate_content_async(self, llm_request, stream=False):
    max_retries = 5
    delay = 15
    for attempt in range(max_retries):
        try:
            async for chunk in original_generate_content_async(llm_request, stream=stream):
                yield chunk
            return
        except Exception as e:
            err_str = str(e).lower()
            transient_terms = ["429", "resource_exhausted", "quota", "too many requests", "503", "unavailable", "high demand", "overloaded"]
            if any(term in err_str for term in transient_terms):
                if attempt < max_retries - 1:
                    print(f"[RETRY-ASYNC] Model call hit transient error ({err_str[:60]}...). Retrying in {delay}s (Attempt {attempt+1}/{max_retries})...", file=sys.stderr)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
            raise e

object.__setattr__(model_instance, "generate_content_async", types.MethodType(wrapped_generate_content_async, model_instance))





# Create local MCP Toolsets
mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="python",
        args=["-m", "app.mcp_server"]
    )
)

kanoon_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="python",
        args=["-m", "app.indian_kanoon_mcp"]
    )
)

search_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="python",
        args=["-m", "app.google_search_mcp"]
    )
)

async def run_node_with_retry(ctx: Context, node, node_input, max_retries=5, delay=15) -> str:
    """Runs a node with transient retry logic for Gemini API 429 rate limits or 503 service overloads."""
    for attempt in range(max_retries):
        try:
            return await ctx.run_node(node, node_input=node_input)
        except Exception as e:
            err_str = str(e).lower()
            transient_terms = ["429", "resource_exhausted", "quota", "too many requests", "503", "unavailable", "high demand", "overloaded"]
            if any(term in err_str for term in transient_terms):
                if attempt < max_retries - 1:
                    print(f"[RETRY] Hit transient Gemini error ({err_str[:60]}...). Retrying in {delay}s (Attempt {attempt+1}/{max_retries})...", file=sys.stderr)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)  # Exponential backoff, cap at 60s
                    continue
            raise e


# ---------------------------------------------------------------------------
# Specialized Agents
# ---------------------------------------------------------------------------

document_classifier_agent = Agent(
    name="document_classifier_agent",
    model=model_instance,
    instruction=(
        "You are a legal document classifier and extractor for Indian notices.\n"
        "Analyze the notice text and classify it into one of these types: "
        "eviction notice, police summons, court order, bank recovery, consumer notice, other.\n"
        "Extract: sender name, recipient name, subject matter, and any dates mentioned.\n"
        "Format your response as a valid JSON object with the keys: "
        "document_type, sender, recipient, subject, dates (list of strings)."
    ),
)

rights_explainer_agent = Agent(
    name="rights_explainer_agent",
    model=model_instance,
    instruction=(
        "You are an expert Indian Legal Rights Explainer. Your goal is to explain legal notices "
        "and inform users of their rights under Indian law. "
        "Use the `lookup_indian_code`, `search_cases`, `get_document` and `google_search` tools to search for relevant laws, judgments, and recent amendments.\n"
        "Explain in plain, simple English (and optionally provide a brief Hindi translation if appropriate):\n"
        "1. What this document means in simple terms.\n"
        "2. What the person is being asked to do.\n"
        "3. What their specific legal rights and protections are (cite relevant sections like Section 106 Transfer of Property Act, SARFAESI 13(2), etc.).\n"
        "Always end with: 'This is not legal advice. Please consult a licensed advocate for serious matters.'"
    ),
    tools=[mcp_toolset, kanoon_mcp_toolset, search_mcp_toolset],
)

deadline_tracker_agent = Agent(
    name="deadline_tracker_agent",
    model=model_instance,
    instruction=(
        "You are a Legal Deadline Tracker for Indian notices.\n"
        "Identify all explicit or implied deadlines in the notice. Use the `calculate_notice_deadline` tool "
        "to calculate the exact deadline date and days remaining from today.\n"
        "Use these guidelines for implied deadlines if not explicitly written:\n"
        "- Eviction notice: 15 days or 30 days under rent control/TPA.\n"
        "- Police Summons: immediate or within 3 days.\n"
        "- Bank Recovery (SARFAESI): 60 days from notice date.\n"
        "- Consumer Notice: 15 days.\n"
        "Classify urgency as:\n"
        "- CRITICAL: under 3 days remaining\n"
        "- URGENT: under 7 days remaining\n"
        "- MODERATE: under 30 days remaining\n"
        "- SAFE: over 30 days remaining\n"
        "If CRITICAL, output a prominent bold warning at the very top: '⚠️ CRITICAL WARNING: Seek immediate legal help from a licensed advocate before drafting or sending a response!'"
    ),
    tools=[mcp_toolset],
)

response_drafter_agent = Agent(
    name="response_drafter_agent",
    model=model_instance,
    instruction=(
        "You are a Legal Response Drafter for Indian legal notices.\n"
        "Generate a formal legal reply letter based on the notice details, the person's rights, and the deadline urgency.\n"
        "If the deadline is tight (CRITICAL/URGENT), include a polite request for an extension of time (e.g. 15-30 days).\n"
        "Ensure the reply disputes any false claims and asserts the person's rights without admitting liability prematurely.\n"
        "Format it as a proper letter with: Date, To (recipient), From (sender), Subject, Salutation, Body, and Signature block.\n"
        "Also generate a plain-language summary explaining what the drafted letter says in 3 simple bullet points.\n"
        "Always append the legal disclaimer using the `generate_legal_disclaimer` tool at the bottom."
    ),
    tools=[mcp_toolset],
)

# ---------------------------------------------------------------------------
# Workflow Nodes
# ---------------------------------------------------------------------------

@node(name="security_checkpoint")
async def security_checkpoint(ctx: Context, node_input: str) -> str:
    """Pre-LLM security screen that sanitises inputs, scrubs PII, and validates documents."""
    text_content = node_input.strip()
    
    # 1. File Path Validation & Size Limit Check (5MB)
    is_file_path = False
    if len(text_content) < 300:
        cleaned_path = text_content.strip("'\"")
        _, ext = os.path.splitext(cleaned_path.lower())
        # Treat as file path only if it has a valid extension name, and either exists on disk or contains no spaces
        if ext and len(ext) > 1 and ext[1:].isalnum() and (os.path.exists(cleaned_path) or " " not in cleaned_path):
            is_file_path = True
            valid_extensions = [".pdf", ".png", ".jpg", ".jpeg", ".webp"]
            if ext not in valid_extensions:
                ctx.state["security_warning"] = (
                    f"Security Exception: Invalid file format '{ext}'. Only PDF or image files (PNG, JPG, JPEG, WEBP) are allowed."
                )
                ctx.route = "SECURITY_EVENT"
                return "SECURITY_EVENT"
            if not os.path.exists(cleaned_path):
                ctx.state["security_warning"] = f"File not found: '{cleaned_path}'."
                ctx.route = "SECURITY_EVENT"
                return "SECURITY_EVENT"
            # File size limit check (max 5MB)
            file_size = os.path.getsize(cleaned_path)
            if file_size > 5 * 1024 * 1024:
                ctx.state["security_warning"] = (
                    f"Security Exception: File size {file_size / (1024*1024):.2f}MB exceeds the maximum allowed limit of 5.00MB."
                )
                ctx.route = "SECURITY_EVENT"
                return "SECURITY_EVENT"

    # Define PII patterns for scrubbing
    aadhar_pattern = r'\b\d{4}\s\d{4}\s\d{4}\b|\b\d{12}\b'
    pan_pattern = r'\b[A-Z]{5}\d{4}[A-Z]\b'
    phone_pattern = r'\b[6-9]\d{9}\b'
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

    # 2. Extract text if it is a file path with limits verification
    extracted_text = text_content
    if is_file_path:
        cleaned_path = text_content.strip("'\"")
        if cleaned_path.lower().endswith(".pdf"):
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(cleaned_path)
                # Page count limit check (max 10 pages)
                if doc.page_count > 10:
                    doc.close()
                    ctx.state["security_warning"] = (
                        f"Security Exception: PDF has {doc.page_count} pages, which exceeds the allowed limit of 10 pages."
                    )
                    ctx.route = "SECURITY_EVENT"
                    return "SECURITY_EVENT"
                pages_text = [page.get_text() for page in doc]
                doc.close()
                extracted_text = "\n".join(pages_text)
            except Exception as e:
                # Scrub the exception of any PII to prevent disclosure in logs
                error_msg = str(e)
                error_msg = re.sub(aadhar_pattern, "[AADHAAR_REDACTED]", error_msg)
                error_msg = re.sub(pan_pattern, "[PAN_REDACTED]", error_msg)
                error_msg = re.sub(phone_pattern, "[PHONE_REDACTED]", error_msg)
                ctx.state["security_warning"] = f"Failed to extract text from PDF safely: {error_msg}"
                ctx.route = "SECURITY_EVENT"
                return "SECURITY_EVENT"
        else:
            # Simulate or mock OCR extraction for images safely
            extracted_text = (
                "Notice of appearance/summons issued by Court of Mumbai. "
                "Parties: Landlord Ramesh Shah and Tenant Raj Kumar. Notice dated 2026-06-20. "
                "Subject: Eviction due to non-payment of rent. Please respond within 15 days."
            )

    # 3. Input Sanitisation & Prompt Injection Shield
    sanitised_text = "".join(ch for ch in extracted_text if ch.isalnum() or ch.isspace() or ch in ".,-;:()[]/@_#")
    
    injection_keywords = [
        "ignore all previous", "ignore instruction", "system prompt",
        "override instruction", "disregard instructions", "developer mode",
        "act as a", "new rules", "jailbreak", "ignore safety", "bypass guidelines"
    ]
    is_injection = any(kw in sanitised_text.lower() for kw in injection_keywords)

    # 4. Reject non-legal documents
    legal_keywords = [
        "notice", "summons", "court", "recovery", "eviction", "complaint", "decree",
        "petitioner", "respondent", "plaintiff", "defendant", "advocate", "under section",
        "tribunal", "hearing", "judge", "bns", "crpc", "cpc", "sarfaesi", "rera", "ipc"
    ]
    is_legal = any(kw in sanitised_text.lower() for kw in legal_keywords)
    
    if not is_legal:
        ctx.state["security_warning"] = (
            "Exception: The uploaded document or input text does not appear to be a legal notice or summons. "
            "Please upload a valid legal notice (eviction notice, court order, bank recovery notice, police summons)."
        )
        ctx.route = "SECURITY_EVENT"
        return "SECURITY_EVENT"

    # 5. PII Scrubbing
    redacted_text = sanitised_text
    redacted_text = re.sub(aadhar_pattern, "[AADHAAR_REDACTED]", redacted_text)
    redacted_text = re.sub(pan_pattern, "[PAN_REDACTED]", redacted_text)
    redacted_text = re.sub(phone_pattern, "[PHONE_REDACTED]", redacted_text)
    redacted_text = re.sub(email_pattern, "[EMAIL_REDACTED]", redacted_text)

    # Store redacted text in state for downstream nodes
    ctx.state["scrubbed_input"] = redacted_text

    # 6. Structured JSON Audit Log (DO NOT write document content to log!)
    severity = "INFO"
    audit_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "pii_redacted": redacted_text != sanitised_text,
        "injection_detected": is_injection,
        "is_legal_document": is_legal,
        "file_path_validated": is_file_path
    }
    
    if is_injection:
        severity = "CRITICAL"
        ctx.state["security_warning"] = (
            "Security Event: Your request contains patterns flagged as prompt injection. Process terminated."
        )
        print(json.dumps({"severity": severity, "event": audit_data}), file=sys.stderr)
        ctx.route = "SECURITY_EVENT"
        return "SECURITY_EVENT"

    print(json.dumps({"severity": severity, "event": audit_data}), file=sys.stderr)
    ctx.route = "ok"
    return "ok"


@node(name="document_reader_agent", rerun_on_resume=True)
async def document_reader_agent(ctx: Context, node_input: str) -> str:
    """Classifies the notice using the pre-scrubbed text in context state."""
    text = ctx.state.get("scrubbed_input", node_input)
    result = await run_node_with_retry(ctx, document_classifier_agent, node_input=text)
    return str(result)


@node(name="orchestrator", rerun_on_resume=True)
async def orchestrator(ctx: Context, node_input: str) -> str:
    """Coordinates the sub-agents and manages the human-in-the-loop workflow."""
    scrubbed_input = ctx.state.get("scrubbed_input", node_input)
    
    # 1. Run Document Reader
    doc_facts_json = await run_node_with_retry(ctx, document_reader_agent, node_input=scrubbed_input)
    ctx.state["doc_facts"] = doc_facts_json
    
    doc_type = "other"
    try:
        facts = json.loads(doc_facts_json)
        doc_type = facts.get("document_type", "other")
    except Exception:
        pass
    
    # 2. Run Rights Explainer and Deadline Tracker
    rights_explanation = await run_node_with_retry(ctx, rights_explainer_agent, node_input=f"Analyze rights for: {doc_facts_json}")
    ctx.state["rights_explanation"] = rights_explanation
    
    deadline_analysis = await run_node_with_retry(ctx, deadline_tracker_agent, node_input=f"Analyze deadlines for: {doc_facts_json}")
    ctx.state["deadline_analysis"] = deadline_analysis
    
    # 3. Pause for Human-in-the-loop facts for response drafting
    interrupt_id = "reply_facts_input"
    if interrupt_id not in ctx.resume_inputs:
        prompt_message = (
            f"--- Notice Analysis ---\n"
            f"Type: {doc_type.upper()}\n\n"
            f"--- Rights Explanation ---\n{rights_explanation}\n\n"
            f"--- Deadline Analysis ---\n{deadline_analysis}\n\n"
            f"Please enter any specific facts or objections you want included in the draft reply letter (or type 'skip' to use default draft):"
        )
        return RequestInput(
            interrupt_id=interrupt_id,
            message=prompt_message
        )
        
    user_facts = ctx.resume_inputs[interrupt_id]
    if isinstance(user_facts, dict) and "result" in user_facts:
        user_facts = user_facts["result"]
    elif isinstance(user_facts, dict) and "response" in user_facts:
        user_facts = user_facts["response"]
        
    ctx.state["user_facts"] = str(user_facts)
    
    # 4. Run Response Drafter
    response_draft = await run_node_with_retry(
        ctx,
        response_drafter_agent,
        node_input=(
            f"Draft response for: {doc_facts_json}.\n"
            f"User custom facts/objections: {user_facts}.\n"
            f"Rights: {rights_explanation}.\n"
            f"Urgency/Deadlines: {deadline_analysis}"
        )
    )
    ctx.state["response_draft"] = response_draft
    
    # 5. Compile consolidated output
    consolidated = (
        f"# Legal First-Aid Report\n\n"
        f"## 📋 Document Details\n{doc_facts_json}\n\n"
        f"## ⚖️ Your Legal Rights & Explanation\n{rights_explanation}\n\n"
        f"## ⏳ Deadline & Urgency Analysis\n{deadline_analysis}\n\n"
        f"## 📝 Draft Response Letter\n{response_draft}\n"
    )
    return consolidated


@node(name="final_output")
async def final_output(ctx: Context, node_input: str) -> str:
    """Consolidates the final response and programmatically enforces the disclaimer check."""
    if "security_warning" in ctx.state:
        return ctx.state["security_warning"]
        
    orchestrator_output = node_input
    
    mandatory_phrase = "Under the Advocates Act, 1961"
    disclaimer = (
        "\n\n***\n"
        "Disclaimer: This analysis and response template are AI-generated for informational and educational purposes only. "
        "It does NOT constitute legal advice or create an advocate-client relationship. Under the Advocates Act, 1961, and "
        "rules of the Bar Council of India, legal advice must only be provided by qualified advocates. Please consult a licensed "
        "advocate for any formal legal action."
    )
    
    if mandatory_phrase not in orchestrator_output:
        orchestrator_output += disclaimer
        
    return orchestrator_output

# ---------------------------------------------------------------------------
# Application & Graph Setup
# ---------------------------------------------------------------------------

workflow_graph = Workflow(
    name="legal_first_aid_workflow",
    edges=[
        ("START", security_checkpoint),
        (security_checkpoint, {"ok": orchestrator, "SECURITY_EVENT": final_output}),
        (orchestrator, final_output)
    ]
)

root_agent = workflow_graph

app = App(
    root_agent=workflow_graph,
    name="app",
)
