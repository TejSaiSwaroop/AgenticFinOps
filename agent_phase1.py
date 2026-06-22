from datetime import datetime, timedelta
from time import timezone
from openai import OpenAI
from dotenv import load_dotenv
import os

from sqlalchemy import update
from database.db import SessionLocal
from database.models import Employee, ExpensePolicy, Transaction, Investigation
import json
import requests
from database.common import run_sql_query, run_modify_sql


load_dotenv()

deepseek_base_url = "https://api.deepseek.com/v1"
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

# for Telegram
telegram_bot_token = os.getenv("TELEGRAM_TOKEN")
telegram_chatid = os.getenv("TELEGRAM_CHATID")

# deeepseek model
deepseek_client = OpenAI(base_url=deepseek_base_url, api_key=deepseek_api_key)

status_map = {
    'approved': 'completed',
    'rejected': 'cancelled',
    'escalated': 'pending_review'
}

def get_employee_profile(employee_id: str):
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

def get_expense_policy_profile(category: str):
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
                "transaction_status": t.transaction_status,
                "agent_decision": t.agent_decision,
                "HIL_status":t.HIL_status
            })

        # transactions summary
        total_spent = sum(t.amount for t in transactions)
        avg_transaction = total_spent/len(transactions)
        categories = list(set((t.category for t in transactions)))
        flagged_count = sum(1 for t in transactions if t.transaction_status == "flagged")
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

def search_past_investigations(query: str, max_results: int = 3):
    sql = "SELECT id, employee_id, category, amount, agent_decision, reasoning, created_at FROM investigations"
    data = run_sql_query(sql)
    
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data)  # pass error to LLM as JSON string
    
    # Simple keyword matching: check if query words appear in reasoning or category
    keywords = query.lower().split()
    scored = []
    for row in data:
        text_to_search = f"{row.get('category','')} -----> {row.get('reasoning','')}".lower()
        print("\n----------------------text-----------------------\n",text_to_search,"\n----------------------text-----------------------\n")
        score = sum(1 for kw in keywords if kw in text_to_search)
        if score > 0:
            scored.append((score, row))
    
    # Sort by score descending, take top max_results
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [row for score, row in scored[:max_results]]

    print("---------------------------------------")
    print(top)
    print("---------------------------------------\n")
    
    if not top:
        return json.dumps({"message": "No similar past cases found."})
    
    return json.dumps(top, default=str)  # default=str to handle datetime serialization


def save_investigation(transaction_id, employee_id, category, amount, decision, reasoning, evidence_summary):
    session = SessionLocal()
    try:
        investigation = Investigation(
            transaction_id=transaction_id,
            employee_id=employee_id,
            category=category,
            amount=amount,
            agent_decision=decision,
            reasoning=reasoning,
            evidence_summary=evidence_summary
        )
        session.add(investigation)
        if decision.lower() in ['approved', 'rejected', 'escalated']:
            new_status = status_map.get(decision.lower())
            if new_status:
                update_transaction = (update(Transaction)
                    .where(Transaction.id == transaction_id)
                    .values(agent_decision=decision.lower(),
                            transaction_status=new_status))
            session.execute(update_transaction)
        session.commit()
        return f"Transaction status updated and Decision is {decision} and details saved in Investigations"

    except Exception as e:
        print(f"Failed to save investigation: {e}")
        return f"Failed to save investigation: {e}"
    finally:
        session.close()   

get_employee_profile_json = {
    "name": "get_employee_profile",
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

search_past_investigations_json = {
    "name": "search_past_investigations",
    "description": "Search past investigations for cases similar to the current transaction. Use this to find how similar situations were handled before to ensure consistent decisions.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords or a short description to search for (e.g., 'office supplies over limit', 'new merchant electronics')."
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 3). increase the limit if more detials required for the verification."
            }
        },
        "required": ["query"],
        "additionalProperties": False
    }
}

submit_final_decision_json = {
    "name": "submit_final_decision",
    "description": "Submit the agent's final investigation decision. Must be called exactly once at the end of every investigation.",
    "parameters": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["APPROVED", "REJECTED", "ESCALATED"],
                "description": "The agent's decision for the transaction."
            },
            "reasoning": {
                "type": "string",
                "description": "Concise summary of the evidence and reasoning behind the decision."
            }
        },
        "required": ["decision", "reasoning"],
        "additionalProperties": False
    }
}

tools = [{"type": "function", "function": get_employee_profile_json},{"type": "function", "function": get_expense_policy_profile_json}
        ,{"type": "function", "function": get_employee_transaction_history_json},{"type": "function", "function": send_telegram_escalation_json}, 
        {"type": "function", "function": search_past_investigations_json}, {"type": "function", "function": submit_final_decision_json}]

system_prompt = """You are an expense compliance agent at a financial firm who works on behalf of the finance team.
You investigate flagged transactions to determine if they should be approved, rejected or escalated to a human reviewer by analysing them to detect fraud, policy violations and unusual spending patterns.
You are the best in the world in identifying fraud transactions then approving or rejecting transactions based on the data retrieved by the tools.

You have access to the following tools:
- get_employee_profile(employee_id: str): Returns the employee's policy limit, risk tier, and manager's Slack ID as a JSON object.
- get_expense_policy(category: str): Returns the company's expense policy for the given category, including max_amount, whether a receipt is required, and any additional notes.
- get_employee_transaction_history(emp_id: str, days: int): Returns recent transactions with statistics for pattern analysis. Each transaction record includes:
    - transaction_status: the current lifecycle state (completed, cancelled, flagged, pending_review, failed).
    - agent_decision: the final decision made by the compliance system (approved or rejected).
    - HIL_status: if the transaction was escalated, this shows the human reviewer's final decision (approved or rejected). NULL means no human was involved.
- send_telegram_escalation(employee_id, transaction_details, escalation_reason, evidence_summary, employee_slack_id): Sends an instant Telegram alert to the manager with full investigation details. 
  Use this tool IMMEDIATELY after deciding to ESCALATE — it delivers the evidence to the human reviewer.
- search_past_investigations(query: str, max_results: int): Searches past completed investigations for cases similar to the current transaction. Returns a JSON list of the most relevant past cases. 
  Use this when you want to check how similar situations have been handled before to ensure consistent decisions.

Decisions:
- APPROVED: The transaction is normal and within the employee's limits.
- REJECTED: Clear evidence of policy violation or fraud.
- ESCALATE: Uncertain or high-risk; needs a human review.

INVESTIGATION PROTOCOL:
For every flagged transaction, follow this sequence:
1. ALWAYS fetch the employee profile first to understand their limits and risk level.
2. ALWAYS check the category policy to know the rules.
3. Always base your decisions on the data from transaction history. The agent_decision and HIL_status fields show you how past transactions were resolved — use these to maintain consistency. Even escalated transactions are updated by the employee's manager, so their final outcome is visible.
4. If the transaction seems unusual or you are uncertain, fetch the employee's transaction history to:
   - Compare against typical spending in this category
   - Look for sudden spikes or frequency changes
   - Identify if similar transactions were previously escalated or rejected (check agent_decision field)
   - Check if the merchant is new or unusual
   - Review past HIL_status to see how humans resolved similar escalations
   - After reviewing the history, if you still need more context or want to ensure consistency, optionally call search_past_investigations with a query summarising the current situation 
    (e.g., “office supplies over policy limit new merchant”). Use the results to inform your decision, if a nearly identical case was approved/rejected/escalated before, 
    that should heavily influence your choice.
5. If your decision is ESCALATE, you MUST call send_telegram_escalation BEFORE giving your FINAL_ANSWER.
   The tool call sends the alert; the FINAL_ANSWER documents the outcome.

ESCALATION RULES:
- ALWAYS escalate if the employee's risk tier is "high" and the merchant is new.
- Always escalate if the transaction amount overage is less than 4% of the expense policy limit for the category. If the overage is more than 4%, then REJECT the transaction.
- ALWAYS escalate if historical patterns show a sudden, unexplained spike.
- If you escalate, include all evidence so the manager can decide immediately.

MANDATORY THINKING STEP:
Before calling any tool (except submit_final_decision), you MUST FIRST output a single line that starts with [THINK]: 
followed by your reasoning about what you currently know, what you need to find out, and why the next tool is the right one.

After you output [THINK]:, do NOT call a tool in the same response. The system will record your thought and then give you another turn. On the NEXT turn, call the tool.

Example:
Turn 1:
[THINK]: I need the employee profile to check limits and risk tier.

Turn 2 (system gives you another chance):
Tool call: get_employee_profile(employee_id="E103")

Never output [THINK] before submit_final_decision. For the final decision, call submit_final_decision directly.

FINAL DECISION: When you have reached a decision, you MUST call the function (tool) "submit_final_decision" with your decision and reasoning. Do not output text. call the tool. 
This is how the system records your investigation. If your decision is ESCALATE, you must have already called send_telegram_escalation before calling submit_final_decision.

FINAL_ANSWER: APPROVED|REJECTED|ESCALATED
Your decision will be automatically recorded in the transaction as agent_decision, and the transaction_status will be updated accordingly.

Important: Never reject a transaction solely on suspicion. You must base your decision on the data retrieved by the tools.
Never approve a transaction just because it looks valid. You must base your decision on the data retrieved by the tools for each employee.
Always escalate a transaction when you find any discrepancy, even a minor thing that causes a doubt.
"""

def run_agent(user_goal: str) -> str:
    print(user_goal)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_goal},
        {"role": "assistant", "content": "[THINK]: I will now begin the investigation by gathering the necessary data."}
    ]
    max_turns = 10
    call_counter = {}

    for _ in range(max_turns):
        print(_)
        response = deepseek_client.chat.completions.create(model="deepseek-v4-pro", messages=messages, tools=tools)

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason 
        warning = ""
        # If the LLM wants to call a tool
        if finish_reason == "tool_calls":
            messages.append(msg.model_dump())
            tool_calls = msg.tool_calls
            
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                print( tool_name)
                tool_args = json.loads(tool_call.function.arguments)

                if tool_name == "submit_final_decision":
                    decision = tool_args["decision"]
                    reasoning = tool_args["reasoning"]
                    print("\n----------------------")
                    print(reasoning)
                    print("----------------------\n")

                    # Collect evidence from previous tool messages
                    evidence_summary = ".\n".join(msg["content"] for msg in messages if msg["role"] == "tool")

                    save_investigation(transaction_id, employee_id, category, amount, decision, reasoning, evidence_summary)

                    return decision

                call_signature = (tool_name, json.dumps(tool_args, sort_keys=True))
                call_counter[call_signature] = call_counter.get(call_signature, 0) + 1

                if call_counter[call_signature] == 2:
                    # Warning: same call repeated twice
                    warning = f"[WARNING] Tool - {tool_name} called a second time with identical args."
                    print(f"[WARNING] Tool - {tool_name} called a second time with identical args.")
                elif call_counter[call_signature] >= 3:
                    # Stuck loop detected – escalate immediately
                    reason = f"Agent loop detected: tool '{tool_name}' called {call_counter[call_signature]} times with same arguments."
                    print(reason)
                    # Build escalation details with what we know
                    escalation_msg = send_telegram_escalation(employee_id, f"Transaction {transaction_id}: {amount}$ {category}", reason,
                        "Investigation aborted automatically to prevent infinite loop.", "manager_not_set")
                    # Save the escalation as the final decision
                    save_investigation(transaction_id, employee_id, category, amount, "escalated", reason, escalation_msg)
                    return reason

                tool = globals().get(tool_name)
                result = tool(**tool_args) if tool else json.dumps({"error": f"tool - '{tool_name}' not found"})
            # OBSERVE: Add the tool result to memory as a "tool" role message
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
                if warning:
                    messages.append({"role": "system", "content": warning})

        else:
            final_text = msg.content
            if final_text and final_text.startswith("[THINK]:"):
                # Append the thought to memory, continue loop
                messages.append({"role": "assistant", "content": final_text})
                print(final_text)
                continue
            else:
                return final_text

    return "Agent reached max turns without finalizing."


def ensure_transaction_saved(txn_id, emp_id, amount, category, merchant=None, date=None):
    session = SessionLocal()
    try:
        txn = session.query(Transaction).filter(Transaction.id == txn_id).first()
        if not txn:
            new_txn = Transaction(
                id=txn_id,
                employee_id=emp_id,
                category=category,
                amount=amount,
                date= date if date else datetime.today(),
                merchant=merchant,
                transaction_status='flagged'                
            )
            session.add(new_txn)
            session.commit()
            print(f"Transaction {txn_id} recorded.")
        else:
            print(f"Transaction {txn_id} already exists.")
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


transaction_id = "T2206"
amount = 240.00
category = "Software"
employee_id = "E104"
merchant= "Slack"

# inserting the transaction in the transaction table to ensure that it exists in transactions
ensure_transaction_saved(transaction_id, employee_id, amount, category, merchant)

goal = f"Investigate transaction {transaction_id} of amount: {str(amount)}$ in category: {category} with merchant - {merchant} of employee with employee_id: {employee_id}"

final_decision = run_agent(goal)

print("\n", final_decision)
