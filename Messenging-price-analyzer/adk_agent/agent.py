from google.adk import agents

# Import the tools you expose to the agent
from adk_agent.tools import (
    run_daily_pipeline,
    fetch_emails,          # safe: respects USE_GRAPH / MOCK_EMAIL, uses local inbox in mock
    extract_rows,
    diff_and_snapshot,
    render_html,
    send_summary_email,
)

# Keep the planning model on a name your key supports (from your list_models output)
root_agent = agents.Agent(
    name="sms_price_change_agent",
    instruction=(
        "You are a pragmatic ops agent for monitoring supplier SMS price changes. "
        "Your job: fetch emails, extract price rows from email bodies & attachments, "
        "diff against the last snapshot, render an HTML summary, and (optionally) email it. "
        "Prefer short, deterministic steps. If a step already produced an artifact (e.g., the latest diff), reuse it. "
        "For email, call send_summary_email. Never ask for secrets; they come from env. "
        "If Graph is disabled or in mock mode, fetch_emails uses the local inbox folder instead of Microsoft Graph."
    ),
    # IMPORTANT: use a model that exists for your API key. You confirmed these from your list.
    model="gemini-2.5-flash",
    tools=[
        run_daily_pipeline,
        fetch_emails,
        extract_rows,
        diff_and_snapshot,
        render_html,
        send_summary_email,
    ],
)
