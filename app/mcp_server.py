import sys
from mcp.server import FastMCP

mcp = FastMCP("Legal First-Aid MCP Server")

@mcp.tool()
def lookup_indian_code(keyword: str) -> str:
    """Searches for relevant sections of Indian law (CPC, CrPC, BNS/IPC, etc.) based on keywords.

    Args:
        keyword: The keyword to search for (e.g. "eviction", "summons", "consumer").
    """
    keyword_clean = keyword.lower().strip()
    if "eviction" in keyword_clean or "tenant" in keyword_clean or "rent" in keyword_clean:
        return (
            "1. Transfer of Property Act, 1882 - Section 106: Requires a written notice to terminate a lease (15 days notice for monthly leases).\n"
            "2. State Rent Control Acts (e.g., Maharashtra Rent Control Act Section 15, Delhi Rent Control Act Section 14): "
            "A landlord cannot evict a tenant who is willing to pay rent, except under specific grounds (non-payment, subletting, personal bona fide use) "
            "and only after serving an eviction notice and obtaining a court order."
        )
    elif "summon" in keyword_clean or "police" in keyword_clean or "crpc" in keyword_clean or "bns" in keyword_clean:
        return (
            "1. Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023 / Code of Criminal Procedure (CrPC) - Section 35 (formerly Sec 41A CrPC): "
            "Notice of appearance before a police officer. The person notice is served on is duty-bound to comply. No arrest can be made unless recorded in writing.\n"
            "2. BNSS / CrPC - Section 64 (formerly Sec 61 CrPC): Form of summons. Every summons issued by a court must be in writing, in duplicate, signed by the presiding officer, and bear the seal of the court."
        )
    elif "court order" in keyword_clean or "injunction" in keyword_clean or "cpc" in keyword_clean:
        return (
            "1. Code of Civil Procedure (CPC), 1908 - Order 39, Rules 1 & 2: Temporary injunctions to preserve status quo. "
            "Must be served to the other party, and disobedience can lead to civil prison or property attachment.\n"
            "2. CPC Section 96: Appeal from original decree. A party aggrieved by a court order has the right to appeal within the prescribed limitation period."
        )
    elif "bank" in keyword_clean or "recovery" in keyword_clean or "loan" in keyword_clean or "sarfaesi" in keyword_clean:
        return (
            "1. SARFAESI Act, 2002 - Section 13(2): Demand Notice. Gives borrower 60 days to discharge liabilities. "
            "Under Section 13(3A), the borrower has the right to submit a representation/objection, and the secured creditor MUST respond within 15 days.\n"
            "2. Recovery of Debts and Bankruptcy Act (RDB Act): Banks can file an application in the Debt Recovery Tribunal (DRT) for recovery."
        )
    elif "consumer" in keyword_clean or "notice" in keyword_clean or "complaint" in keyword_clean:
        return (
            "1. Consumer Protection Act, 2019 - Section 35: A consumer can file a complaint in the District Commission for any unfair trade practice, defective good, or deficient service. "
            "Before filing, a legal notice is usually sent giving 15-30 days to resolve the dispute."
        )
    else:
        return (
            "For general notices in India, Section 80 of the Code of Civil Procedure (CPC) is relevant for suits against the government, requiring a 2-month notice period. "
            "In commercial contracts, notice terms are governed by the contract's dispute resolution and termination clauses."
        )

@mcp.tool()
def calculate_notice_deadline(notice_date_str: str, notice_period_days: int) -> str:
    """Computes the exact calendar date response deadline from a notice date and notice period.

    Args:
        notice_date_str: The date on the notice in YYYY-MM-DD format.
        notice_period_days: The response period in days (e.g. 15, 30, 60).
    """
    import datetime
    try:
        notice_date = datetime.datetime.strptime(notice_date_str.strip(), "%Y-%m-%d").date()
    except Exception:
        try:
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    notice_date = datetime.datetime.strptime(notice_date_str.strip(), fmt).date()
                    break
                except ValueError:
                    continue
            else:
                return f"Error: Notice date '{notice_date_str}' must be in YYYY-MM-DD format."
        except Exception as e:
            return f"Error parsing date: {str(e)}"

    deadline_date = notice_date + datetime.timedelta(days=notice_period_days)
    today = datetime.date.today()
    days_remaining = (deadline_date - today).days

    weekday_name = deadline_date.strftime("%A")
    warning = ""
    if weekday_name in ("Saturday", "Sunday"):
        warning = f" (Warning: This deadline falls on a {weekday_name}. It is highly recommended to submit the response by the preceding Friday.)"

    return f"Deadline Date: {deadline_date.strftime('%Y-%m-%d')} ({weekday_name}). Days remaining: {days_remaining} days.{warning}"

@mcp.tool()
def generate_legal_disclaimer() -> str:
    """Returns the standard legal disclaimer statement required for AI-generated legal assistance in India."""
    return (
        "Disclaimer: This analysis and response template are AI-generated for informational and educational purposes only. "
        "It does NOT constitute legal advice or create an advocate-client relationship. Under the Advocates Act, 1961, and "
        "rules of the Bar Council of India, legal advice must only be provided by qualified advocates. Please consult a licensed "
        "advocate for any formal legal action."
    )

if __name__ == "__main__":
    mcp.run(transport="stdio")
