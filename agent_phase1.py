from datetime import datetime, timedelta
from time import timezone
from openai import OpenAI
from dotenv import load_dotenv
import os

from sqlalchemy import update, func
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
        expence_policy = session.query(ExpensePolicy).filter(func.lower(ExpensePolicy.category) == category.lower()).first()
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

def search_past_investigations(query: str, max_results: int = 3, employee_id: str = None, category: str = None):
    sql = "SELECT id, employee_id, category, amount, agent_decision, reasoning, created_at FROM investigations"
    conditions = []
    if employee_id:
        conditions.append(f"employee_id = '{employee_id}'")
    if category:
        conditions.append(f"category = '{category}'")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    
    data = run_sql_query(sql)
    
    # If run_sql_query returned an error dict, pass it back
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data)
    
    # data should be a list; if not, wrap it
    if not isinstance(data, list):
        return json.dumps({"message": "Unexpected data format from database."})
    
    keywords = query.lower().split()
    scored = []
    for row in data:
        # Handle both dict and string rows
        if isinstance(row, dict):
            category_text = row.get('category', '')
            reasoning_text = row.get('reasoning', '')
        elif isinstance(row, str):
            # string row – treat as raw text
            category_text = ''
            reasoning_text = row
        else:
            continue  # skip unknown types
        
        text_to_search = f"{category_text} -----> {reasoning_text}".lower()
        score = sum(1 for kw in keywords if kw in text_to_search)
        if score > 0:
            scored.append((score, row))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [row for _, row in scored[:max_results]]
    
    if top:
        print("-----------------Top----------------------")
        print(top)
        print("-----------------Top----------------------\n")
        return json.dumps(top, default=str)  # default=str to handle datetime serialization
    else:
        return json.dumps({"message": "No similar past cases found."})


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
                "description": "Maximum number of results (default 3). Increase the limit if more detials required for the Investigation."
            },
            "employee_id": {
                "type": "string",
                "description": "Optional. Filter to only this employee's past investigations."
            },
            "category": {
                "type": "string",
                "description": "Optional. Filter to only this category."
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

THINK_SYSTEM_PROMPT = """You are the THINK phase of an expense compliance agent at a financial firm.
Your job is to analyse the current flagged transaction and identify what information you still need to make a confident decision.

You do NOT call tools. You only describe the gaps in your knowledge.
You know the system can provide:
- Employee profile (policy limit, risk tier, manager contact)
- Expense category policy (max amount, receipt required, notes)
- Employee’s recent transaction history (patterns, statuses, past decisions)
- Past similar investigations (how they were resolved, including human overrides)
- A way to escalate to a human reviewer if needed

Based on what you already know about the transaction, describe what specific data you require next.
- DO NOT mention any tool names.
- DO NOT say you are "calling" or "will call" a tool.
- Only state the information gaps and why they matter.

Output a single line starting with [THINK]:.

Example:
[THINK]: I need the employee profile to check limits and risk tier, and the expense policy to understand the rules for this category.

Nothing else related to tools invoking or calling is required in the output. You should just give the analysis like the above example. 
"""

ACT_SYSTEM_PROMPT = """You are the ACTION phase of the world’s best expense compliance agent.
You receive the Think agent’s analysis of what data is still needed. Your job is to call the required tools to gather that data, then make a final decision.

You have NOT called any tools yet. All tool calls must be made by you now.

You have access to the following tools:
- get_employee_profile(employee_id: str): Returns the employee's policy limit, risk tier, and manager's Slack ID as a JSON object.
- get_expense_policy(category: str): Returns the company's expense policy for the given category, including max_amount, whether a receipt is required, and any additional notes.
- get_employee_transaction_history(emp_id: str, days: int): Returns recent transactions with statistics for pattern analysis. Each transaction record includes:
    - transaction_status: the current lifecycle state (completed, cancelled, flagged, pending_review, failed).
    - agent_decision: the final decision made by the compliance system (approved or rejected).
    - HIL_status: if the transaction was escalated, this shows the human reviewer's final decision (approved or rejected). NULL means no human was involved.
- send_telegram_escalation(employee_id, transaction_details, escalation_reason, evidence_summary, employee_slack_id): Sends an instant Telegram alert to the manager with full investigation details. Use this tool IMMEDIATELY after deciding to ESCALATE.
- search_past_investigations(query, max_results, employee_id, category): Searches past completed investigations for cases similar to the current transaction. ALWAYS include the current employee_id and category for precise results. Use this to check how similar situations were handled before.
- submit_final_decision(decision, reasoning): Submits your final decision. decision must be APPROVED, REJECTED, or ESCALATED. reasoning is a concise summary of your evidence.

Decisions:
- APPROVED: The transaction is normal and within the employee's limits.
- REJECTED: Clear evidence of policy violation or fraud.
- ESCALATE: Uncertain or high-risk; needs a human review.

INVESTIGATION PROTOCOL (follow this order):
1. ALWAYS fetch the employee profile first.
2. ALWAYS check the category policy.
3. Base your decisions on transaction history: agent_decision and HIL_status show how past transactions were resolved.
4. If the transaction seems unusual, fetch the employee's transaction history to:
   - Compare against typical spending in this category
   - Look for sudden spikes or frequency changes
   - Identify if similar transactions were previously escalated or rejected
   - Check if the merchant is new or unusual
   - Review HIL_status for human decisions
   - Optionally call search_past_investigations with the current employee_id and category for deeper context.
5. If your decision is ESCALATE, you MUST call send_telegram_escalation BEFORE calling submit_final_decision.

STRICT TOOL USE:
Only call the tools listed above. Do NOT invent new tool names. If no suitable tool exists, use the closest available tool or call submit_final_decision with the best decision you can make.

ESCALATION RULES:
- ALWAYS escalate if the employee's risk tier is "high" and the merchant is new.
- If the transaction amount overage is ≤4% of the category policy limit → ESCALATE. If overage >4% → REJECT.
- ALWAYS escalate if historical patterns show a sudden, unexplained spike.
- Include all evidence in the escalation.

FINAL DECISION: When you are ready, call submit_final_decision with your decision and reasoning. Do not output text – only the tool call. If ESCALATE, you must have already called send_telegram_escalation.

Important: Never reject solely on suspicion. Always base decisions on data. When in doubt, escalate.
"""

def run_agent(transaction_id: str, employee_id: str, amount: float, category: str, merchant: str = "") -> str:
    amount_str = f"{amount:.2f}" if isinstance(amount, float) else str(amount)
    user_goal = f"Investigate transaction {transaction_id} of amount: {amount_str}$ in category: {category} with merchant - {merchant} of employee with employee_id: {employee_id}"
    print(user_goal)
    messages = [{"role": "system", "content": THINK_SYSTEM_PROMPT}, {"role": "user", "content": user_goal}]

    max_turns = 10
    call_counter = {}

    for turn in range(max_turns):
        print(turn)
        # <-- forces text output
        messages[0] ={"role": "system", "content": THINK_SYSTEM_PROMPT}
        think_response = deepseek_client.chat.completions.create(model="deepseek-v4-pro", messages=messages, tools=tools, tool_choice="none")
        think_msg = think_response.choices[0].message
        # Append the thought (may already start with [THINK]: or we wrap it)
        messages.append({"role": "assistant", "content": think_msg.content})
        print(think_msg.content)
        
        # --- ACT PHASE (tool_choice="auto") ---
        messages[0] = {"role": "system", "content": ACT_SYSTEM_PROMPT}
        act_response = deepseek_client.chat.completions.create(model="deepseek-v4-pro", messages=messages, tools=tools)
    
        act_msg = act_response.choices[0].message
        finish_reason = act_response.choices[0].finish_reason
 
        warning = ""
        # If the LLM wants to call a tool
        if finish_reason == "tool_calls":
            messages.append(act_msg.model_dump())
            tool_calls = act_msg.tool_calls
            
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                print(tool_name)
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
            final_text = act_msg.content
            if final_text:
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

# T3001 ($120, Office Supplies, E100).
t_id = "T2217"
amt = 120.00
ctgry = "Office Supplies"
empl_id = "E100"
merch= "Staples"

# inserting the transaction in the transaction table to ensure that it exists in transactions
ensure_transaction_saved(t_id, empl_id, amt, ctgry, merch)

final_decision = run_agent(t_id, empl_id, amt, ctgry, merch)

print("\n Final Decision ---> \n\n\n----->\n", final_decision)
