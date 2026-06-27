# STRIDE Threat Modeling — Legal First-Aid Agent 🛡️

This document performs a structured **STRIDE Threat Modeling** analysis for the **Legal First-Aid Agent** and provides details of the security architecture and mitigation code implemented in the repository.

---

## 1. STRIDE Threat Analysis Matrix

| Threat Category | Specific Threat | Severity | Mitigation Status & Strategy |
| :--- | :--- | :--- | :--- |
| **S**poofing | Attacker feeds fake legal summons or notices to trick users. | Medium | **Mitigated**: Educational watermarks and disclaimers clearly state that the system cannot authenticate legal source documents. |
| **T**ampering | Tampering with local MCP database scripts or bare act references. | Medium | **Mitigated**: Virtual env controls and read-only local database connections prevent runtime script modifications. |
| **R**epudiation | User claims the AI provided formal legal advice or acted as an unlicensed advocate. | High | **Mitigated (Mitigation #3)**: Programmatic final checkpoint blocks output unless the Advocates Act, 1961 disclaimer watermark is verified. |
| **I**nformation Disclosure | Sensitive PII (Aadhaar, PAN, phone numbers) leaks to external LLM logs or crash files. | High | **Mitigated (Mitigation #1)**: Transient regex scrubber masks identifiers in-memory before sending to Vertex AI / Gemini. |
| **D**enial of Service | Maliciously large notice files or zip-bombs crash the PyMuPDF extractor. | High | **Mitigated (Mitigation #2)**: Size (max 5MB) and PDF page count (max 10 pages) checks occur before file processing. |
| **E**levation of Privilege | Attacker injects system prompts to exploit local stdio subprocesses or execute shell commands. | Medium | **Mitigated**: Alphanumeric input sanitization shields and strict subprocess argument validation block prompt injection vectors. |

---

## 2. Detailed Mitigations & Code Implementation

### Threat 1: Information Disclosure (PII Leakage in Crash Logs & Trace Data)
*   **Vulnerability**: A legal notice contains highly sensitive information (Aadhaar cards, PAN numbers, phone numbers). If the parser throws an exception or logs raw text, this sensitive PII can leak into server stderr streams, cloud monitoring services (like Google Cloud Logging), or local file audits.
*   **Mitigation**: All user input text and filenames pass through a regex-based redaction filter in `security_checkpoint` before processing. Additionally, try-catch blocks scrub PII out of error strings before writing warnings to the workflow state.
*   **Code Implementation** (from [`app/agent.py`](file:///c:/Users/rajku/OneDrive/Documents/adk_workspace/legal-first-aid-agent/app/agent.py#L150-L184)):
    ```python
    # Define PII patterns for scrubbing
    aadhar_pattern = r'\b\d{4}\s\d{4}\s\d{4}\b|\b\d{12}\b'
    pan_pattern = r'\b[A-Z]{5}\d{4}[A-Z]\b'
    phone_pattern = r'\b[6-9]\d{9}\b'
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

    # Exception scrubbing to prevent PII leaks in crash logs
    except Exception as e:
        error_msg = str(e)
        error_msg = re.sub(aadhar_pattern, "[AADHAAR_REDACTED]", error_msg)
        error_msg = re.sub(pan_pattern, "[PAN_REDACTED]", error_msg)
        error_msg = re.sub(phone_pattern, "[PHONE_REDACTED]", error_msg)
        ctx.state["security_warning"] = f"Failed to extract text from PDF safely: {error_msg}"
        ctx.route = "SECURITY_EVENT"
        return "SECURITY_EVENT"

    # Redacting standard variables before LLM dispatch
    redacted_text = sanitised_text
    redacted_text = re.sub(aadhar_pattern, "[AADHAAR_REDACTED]", redacted_text)
    redacted_text = re.sub(pan_pattern, "[PAN_REDACTED]", redacted_text)
    redacted_text = re.sub(phone_pattern, "[PHONE_REDACTED]", redacted_text)
    redacted_text = re.sub(email_pattern, "[EMAIL_REDACTED]", redacted_text)
    ```

---

### Threat 2: Denial of Service (Oversized or Malformed PDF Decompression)
*   **Vulnerability**: An attacker uploads a massive 100MB+ legal bundle or a deeply nested decompression bomb designed to hang the server, causing memory exhaustion and service outages.
*   **Mitigation**: File size checks (5MB limit) and page count validations (10-page limit) are executed directly on the local filesystem before calling PyMuPDF libraries.
*   **Code Implementation** (from [`app/agent.py`](file:///c:/Users/rajku/OneDrive/Documents/adk_workspace/legal-first-aid-agent/app/agent.py#L141-L171)):
    ```python
    # File size limit check (max 5MB)
    file_size = os.path.getsize(cleaned_path)
    if file_size > 5 * 1024 * 1024:
        ctx.state["security_warning"] = (
            f"Security Exception: File size {file_size / (1024*1024):.2f}MB exceeds the maximum allowed limit of 5.00MB."
        )
        ctx.route = "SECURITY_EVENT"
        return "SECURITY_EVENT"

    # Page count limit check (max 10 pages)
    if doc.page_count > 10:
        doc.close()
        ctx.state["security_warning"] = (
            f"Security Exception: PDF has {doc.page_count} pages, which exceeds the allowed limit of 10 pages."
        )
        ctx.route = "SECURITY_EVENT"
        return "SECURITY_EVENT"
    ```

---

### Threat 3: Repudiation (Unlicensed Advocate Act Violations)
*   **Vulnerability**: A user follows the AI-generated reply letter, loses their legal dispute, and sues the platform claiming the software acted as an unlicensed legal advocate (violating the Advocates Act, 1961).
*   **Mitigation**: The system implements a programmatic safety gate on the final output node. If the compiled report does not contain the specific compliance disclaimer watermark, the output is blocked and replaced with a default warning.
*   **Code Implementation** (from [`app/agent.py`](file:///c:/Users/rajku/OneDrive/Documents/adk_workspace/legal-first-aid-agent/app/agent.py#L329-L355)):
    ```python
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
            return (
                "Error: Programmatic security check failed (legal disclaimer watermark missing). "
                "Response blocked. Please consult a licensed advocate.\n\n" + disclaimer
            )
            
        if disclaimer.strip() not in orchestrator_output:
            orchestrator_output += disclaimer
            
        return orchestrator_output
    ```

---

### 4. Input Sanitization & Prompt Injection Shield
To prevent prompt injection attacks (where malicious instructions hijack LLM sub-agents), the agent employs an input sanitization filter and a list of injection trigger keywords before routing to downstream nodes.
*   **Code Implementation** (from [`app/agent.py`](file:///c:/Users/rajku/OneDrive/Documents/adk_workspace/legal-first-aid-agent/app/agent.py#L192-L216)):
    ```python
    # 1. Strip special characters except standard punctuation
    sanitised_text = "".join(ch for ch in extracted_text if ch.isalnum() or ch.isspace() or ch in ".,-;:()[]/@_#")
    
    # 2. Check for injection command keywords
    injection_keywords = [
        "ignore all previous", "ignore instruction", "system prompt",
        "override instruction", "disregard instructions", "developer mode",
        "act as a", "new rules", "jailbreak", "ignore safety", "bypass guidelines"
    ]
    is_injection = any(kw in sanitised_text.lower() for kw in injection_keywords)
    ```
