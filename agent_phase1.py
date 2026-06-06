from datetime import datetime, timedelta
from time import timezone
from openai import OpenAI
from dotenv import load_dotenv
import os
from database.db import SessionLocal
from database.models import Employee, ExpensePolicy, Transaction
import json
import requests

load_dotenv()

deepseek_base_url = "https://api.deepseek.com/v1"
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

# for Telegram
telegram_bot_token = os.getenv("TELEGRAM_TOKEN")
telegram_chatid = os.getenv("TELEGRAM_CHATID")

# deeepseek model
deepseek_client = OpenAI(base_url=deepseek_base_url, api_key=deepseek_api_key)

def get_employee_expense_profile(employee_id: str):
    """Return employee profile as a JSON string for the LLM's observation."""
    session = SessionLocal()
    try:
        employee = session.query(Employee).filter(Employee.id == employee_id).first()
        if employee is None:
            return json.dumps({"error": f"Employee '{employee_id}' not found."})
        # employee profile as a JSON string
        employee_profile = {"employee_id": employee.id,
            "name": employee.name,
            "policy_limit": employee.policy_limit,
            "risk_tier": employee.risk_tier,
            "manager_slack_id": employee.manager_slack_id}
        return json.dumps(employee_profile)

    except Exception as e:
        """Return an error string the LLM can understand"""
        return json.dumps({"error": f"Database error: {str(e)}"})

    finally:
        session.close()

def get_expense_policy(category: str):
    session = SessionLocal()
    try:
        expence_policy = session.query(ExpensePolicy).filter(ExpensePolicy.category == category).first()
        if expence_policy is None:
            return json.dumps({"error": f"category '{category}' not found."})
        expense_policy_profile = {"max_amount":expence_policy.max_amount,
        "category":expence_policy.category,
        "requires_receipt":expence_policy.requires_receipt,
        "note":expence_policy.note
        }
        return json.dumps(expense_policy_profile)

    except Exception as e:
        return json.dumps({"error": f"Database Error: {str(e)}"})

    finally:
        session.close()

def get_employee_transaction_history(emp_id: str, days: int):
    session = SessionLocal()
    cutoff_date = datetime.today() - timedelta(days=days)
    try:
        transactions = session.query(Transaction).filter(Transaction.employee_id == emp_id, Transaction.date >= cutoff_date).order_by(Transaction.date.desc()).limit(25).all()

        if not transactions:
            return json.dumps({"message": f"No transactions found for the employee- {emp_id} in the last {days} days."})
        
        history = []
        for t in transactions:
            history.append({
                "transaction_id": t.id,
                "date": t.date.strftime("%Y-%m-%d"),
                "category": t.category,
                "amount": t.amount,
                "merchant": t.merchant,
                "status": t.status
            })

        # transactions summary
        total_spent = sum(t.amount for t in transactions)
        avg_transaction = total_spent/len(transactions)
        categories = list(set((t.category for t in transactions)))
        flagged_count = sum(1 for t in transactions if t.status == "flagged")
        max_transaction_amount = max(t.amount for t in transactions)
        min_transaction_amount = min(t.amount for t in transactions)

        result = {
            "employee_id": emp_id,
            "period": days,
            "transaction_count": len(transactions),
            "average_transaction": round(avg_transaction,2),
            "max_transaction_amount": round(max_transaction_amount, 2),
            "min_transaction_amount": round(min_transaction_amount, 2),
            "total_spent": round(total_spent, 2),
            "categories_used": categories,
            "flagged_transactions": flagged_count,
            "recent_history": history
        }

        return json.dumps(result)
    
    except Exception as e:
        return json.dumps({"error": f"Database Error: {str(e)}"})

    finally:
        session.close()

def create_escalation_message(employee_id, transaction_details, escalation_reason, evidence_summary, employee_slack_id):
    """Formats a clean, professional Telegram message for escalations."""
    
    message = (
        f"🚨 *EXPENSE ESCALATION*\n\n"
        f"👤 *Employee:* `{employee_id}`\n"
        f"📋 *Transaction:* {transaction_details}\n\n"
        f"⚠️ *Reason for Escalation:*\n"
        f"{escalation_reason}\n\n"
        f"🔍 *Investigation Findings:*\n"
        f"{evidence_summary}\n\n"
        f"📨 *Notify Manager:* @{employee_slack_id}\n\n"
        f"⚡ *Action Required:* Please review and approve or reject this transaction.\n\n"
        f"🤖 _AgenticFinOps | Automated Escalation_")

    return message

def send_telegram_escalation(employee_id, transaction_details, escalation_reason, evidence_summary, employee_slack_id):
    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"

    escalation_message = create_escalation_message(employee_id, transaction_details, escalation_reason, evidence_summary, employee_slack_id)

    # Using MarkdownV2 or HTML is much more stable for multi-agent variables
    payload = {"chat_id": telegram_chatid, "text": escalation_message, "parse_mode": "Markdown"}

    try:
        # Always use json= payload for streaming LLM text to avoid form-encoding corruption
        response = requests.post(url, json=payload)
        response.raise_for_status() 
        return json.dumps({"status": "Success", "platform": "Telegram"})
    except Exception as e:
        if 'response' in locals() and response is not None:
            return json.dumps({"status": "Error", "message": f"Telegram Rejected Payload: {response.text}"})
        return json.dumps({"status": "Error", "message": str(e)})


get_employee_expense_profile_json = {
    "name": "get_employee_expense_profile",
    "description": "extracts the employee profile details from the sql table",
    "parameters": {
        "type": "object",
        "properties": {
            "employee_id": {
                "type": "string",
                "description": "The id of the employee to extract the employee profile from database table."}
        },
        "required":["employee_id"],
        "additional_properties": False
        }}

get_expense_policy_profile_json = {
    "name": "get_expense_policy_profile",
    "description": "extracts the expense policy details from the sql table",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "The category of the expense policy to extract the policy details from database table."}
        },
        "required":["category"],
        "additional_properties": False
        }}

get_employee_transaction_history_json = {
    "name": "get_employee_transaction_history",
    "description": "Retrieves an employee's recent transaction history with summary statistics. Use this to identify spending patterns, unusual amounts or anomalies.",
    "parameters": {
        "type": "object",
        "properties": {
            "emp_id": {
                "type": "string",
                "description": "The employee ID to look up transaction history for."
            },
            "days": {
                "type": "integer",
                "description": "Number of days to look back."
            }
        },
        "required": ["emp_id","days"],
        "additionalProperties": False
    }
}

send_telegram_escalation_json = {
    "name": "send_telegram_escalation",
    "description": "Escalates a suspicious or uncertain transaction to a human manager via Telegram. Use this when the transaction exceeds policy limits, shows unusual patterns or when the agent cannot make a confident decision. This ensures human oversight on high-risk cases.",
    "parameters": {
        "type": "object",
        "properties": {
            "employee_id": {
                "type": "string",
                "description": "The ID of the employee who made the transaction."
            },
            "transaction_details": {
                "type": "string",
                "description": "Summary of the transaction: amount, category, merchant, and date."
            },
            "escalation_reason": {
                "type": "string",
                "description": "The specific reason for escalation (e.g., 'Amount exceeds policy limit by 40%', 'Unusual category for this employee', 'High-risk employee with new merchant')."
            },
            "evidence_summary": {
                "type": "string",
                "description": "Concise summary of investigation findings: policy limits checked, historical spending patterns, risk tier, and any anomalies detected."
            },
            "employee_slack_id": {
                "type": "string",
                "description": "The manager's contact identifier for Telegram notification (stored in the employee's profile)."
            }
        },
        "required": ["employee_id", "transaction_details", "escalation_reason", "evidence_summary", "employee_slack_id"],
        "additionalProperties": False
    }
}

tools = [{"type": "function", "function": get_employee_expense_profile_json},{"type": "function", "function": get_expense_policy_profile_json}
        ,{"type": "function", "function": get_employee_transaction_history_json}]

system_prompt = """You are an expense compliance agent at a financial firm who works on behalf of the finance team.
You investigate flagged transactions to determine if they should be approved, rejected or escalated to a human reviewer by analysing them to detect fraud, policy violations and unusual spending patterns.
You are the best in the world in identifying fraud transactions then approving or rejecting transactions based on the data retrieved by the tools.

You have access to the following tools:
- get_employee_expense_profile(employee_id: str): Returns the employee's policy limit, risk tier, and manager's Slack ID as a JSON object.
- get_expense_policy(category: str): Returns the company's expense policy for the given category, including max_amount, whether a receipt is required, and any additional notes.
- get_employee_transaction_history(emp_id: str, days: int):  Returns recent transactions with statistics for pattern analysis.
- send_telegram_escalation(employee_id, transaction_details, escalation_reason, evidence_summary, employee_slack_id): Sends an instant Telegram alert to the manager with full investigation details. 
  Use this tool IMMEDIATELY after deciding to ESCALATE — it delivers the evidence to the human reviewer.

Decisions:
- APPROVED: The transaction is normal and within the employee's limits.
- REJECTED: Clear evidence of policy violation or fraud.
- ESCALATE: Uncertain or high-risk; needs a human review.

INVESTIGATION PROTOCOL:
For every flagged transaction, follow this sequence:
1. ALWAYS fetch the employee profile first to understand their limits and risk level.
2. ALWAYS check the category policy to know the rules.
3. If the amount seems unusual, fetch transaction history to:
   - Compare against the employee's typical spending in this category
   - Look for sudden spikes or frequency changes
   - Identify if similar transactions were previously flagged
   - Check if the merchant is new or unusual
4. If your decision is ESCALATE, you MUST call send_telegram_escalation BEFORE giving your FINAL_ANSWER.
   The tool call sends the alert; the FINAL_ANSWER documents the outcome.

ESCALATION RULES:
- ALWAYS escalate if the transaction exceeds the policy limit by more than 4%.
- ALWAYS escalate if the employee's risk tier is "high" and the merchant is new.
- ALWAYS escalate if historical patterns show a sudden, unexplained spike.
- If you escalate, include all evidence so the manager can decide immediately.

OUTPUT FORMAT:
- When you need data: Call the appropriate tool. The orchestrator will execute it and return results.
- When you've completed investigation AND called send_telegram_escalation (if escalating): 
  Output only:
  FINAL_ANSWER: APPROVED|REJECTED|ESCALATED
  No additional text or reasoning needed — your investigation is already documented in the tool calls.

Important: Never reject a transaction solely on suspicion. You must base your decision on the data retrieved by the tools.
Never approve a transaction just because it looks valid. You must base your decision on the data retrieved by the tools for each employee.
"""

def run_agent(user_goal: str) -> str:
    print(user_goal)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_goal}
    ]
    max_turns = 10

    for _ in range(max_turns):
        print(_)
        response = deepseek_client.chat.completions.create(model="deepseek-v4-pro", messages=messages, tools=tools)

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # If the LLM wants to call a tool
        if finish_reason == "tool_calls":
            messages.append(msg)
            tool_calls = msg.tool_calls
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                tool = globals().get(tool_name)
                result = tool(**tool_args) if tool else json.dumps({"error": "tool not found"})
            # OBSERVE: Add the tool result to memory as a "tool" role message
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result})

        else:
            # No tool call: the LLM is done
            return msg.content if msg.content else "Agent ended with no output."

    return "Agent reached max turns without finalizing."


# goal = "Investigate transaction T0563: $54 for Meals, employee E789"
goal = "Investigate transaction T123: $158 at Office Supplies, employee E456"
# goal = "Investigate transaction T200: $500 at Office Supplies, employee E456"
# goal = "Investigate transaction T300: $400 at Electronics Store, employee E789"

final_decision = run_agent(goal)

print("\n", final_decision)
