import os
import sys
import httpx
from mcp.server import FastMCP

mcp = FastMCP("Indian Kanoon MCP Server")

API_KEY = os.environ.get("INDIAN_KANOON_API_KEY", "")

@mcp.tool()
async def search_cases(query: str, doc_type: str = "judgments") -> str:
    """Searches judgments and bare acts on Indian Kanoon.

    Args:
        query: The search query string (e.g., "eviction section 106", "SARFAESI demand notice").
        doc_type: Type of document (e.g., "judgments", "acts", "all").
    """
    if not API_KEY or API_KEY == "your_kanoon_key_here":
        query_lower = query.lower()
        if "eviction" in query_lower or "tenant" in query_lower:
            return (
                "Mock Search Results (No API Key):\n"
                "1. docid=182939: Sri Ram Pasricha v. Jagannath, 1976 (Supreme Court) - Eviction petition by co-owner.\n"
                "2. docid=948291: Section 106 of Transfer of Property Act, 1882 - Duration of certain leases in absence of written contract."
            )
        elif "sarfaesi" in query_lower or "bank recovery" in query_lower:
            return (
                "Mock Search Results (No API Key):\n"
                "1. docid=772910: Mardia Chemicals Ltd. v. Union of India, 2004 (Supreme Court) - Validity of SARFAESI Act and Section 13.\n"
                "2. docid=284910: Section 13 of SARFAESI Act, 2002 - Enforcement of security interest."
            )
        else:
            return (
                f"Mock Search Results for '{query}' (No API Key):\n"
                "1. docid=10001: General Bare Act Section relating to query.\n"
                "2. docid=10002: Landmark Supreme Court Case on this keyword."
            )

    headers = {"Authorization": f"Token {API_KEY}"}
    params = {"formInput": f"{query} doctype:{doc_type}" if doc_type != "all" else query}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post("https://api.indiankanoon.org/search/", headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                results = []
                for doc in data.get("docs", [])[:5]:
                    results.append(f"docid={doc.get('tid')}: {doc.get('title')}\nSnippet: {doc.get('headline')}\n")
                return "\n".join(results) if results else "No results found."
            else:
                return f"Error from Indian Kanoon API: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error contacting Indian Kanoon API: {str(e)}"

@mcp.tool()
async def get_document(docid: int) -> str:
    """Fetches the full document text for a given Indian Kanoon document ID.

    Args:
        docid: The unique document ID (tid) from search_cases.
    """
    if not API_KEY or API_KEY == "your_kanoon_key_here":
        if docid == 182939:
            return "Sri Ram Pasricha v. Jagannath, 1976 SC:\nHeld that a co-owner is as much an owner of the property as any sole owner, and can maintain an eviction petition."
        elif docid == 948291:
            return "Section 106 of Transfer of Property Act, 1882:\nIn the absence of a contract or local law or usage to the contrary, a lease of immovable property for agricultural or manufacturing purposes shall be deemed to be a lease from year to year, terminable, on the part of either lessor or lessee, by six months' notice; and a lease of immovable property for any other purpose shall be deemed to be a lease from month to month, terminable, on the part of either lessor or lessee, by fifteen days' notice."
        elif docid == 772910:
            return "Mardia Chemicals Ltd. v. UOI, 2004 SC:\nUpheld the validity of the SARFAESI Act, noting that banks can enforce security interest under Section 13, but the borrower has a right to approach the Debt Recovery Tribunal."
        elif docid == 284910:
            return "Section 13 of SARFAESI Act, 2002:\nAllows a secured creditor to enforce any security interest without intervention of court or tribunal, provided a 60-day demand notice is served and any objections are responded to within 15 days."
        else:
            return f"Mock text for docid={docid}: Under Section 80 of CPC, no suit shall be instituted against the Government or a public officer until the expiration of two months next after notice in writing."

    headers = {"Authorization": f"Token {API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(f"https://api.indiankanoon.org/doc/{docid}/", headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("doc", "No document text available.")
            else:
                return f"Error from Indian Kanoon API: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error contacting Indian Kanoon API: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
