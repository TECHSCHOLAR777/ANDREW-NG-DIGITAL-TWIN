import sys
from pathlib import Path
import json
import time

# Ensure we can import scripts
sys.path.append(str(Path(__file__).resolve().parent))

from persona_engine import (
    generate_digital_twin_response,
    load_user_profile,
    save_user_profile,
    reset_user_profile,
    load_episodic_memory_store,
    save_episodic_memory_store,
)

def run_scenarios():
    print("Resetting memory context...")
    reset_user_profile()
    
    # 10 Scenarios definitions
    scenarios = [
        {
            "id": 1,
            "title": "Core ML Explanation (Gradient Descent)",
            "query": "Can you explain how gradient descent works?",
            "pre_func": None,
            "description": "Tests the 4-step explanation engine, physical analogies (foggy hill), and persona consistency."
        },
        {
            "id": 2,
            "title": "Career Advice for a Beginner",
            "query": "I want to get into ML — where do I start?",
            "pre_func": None,
            "description": "Tests the T-shaped knowledge framework, practical advice register, and structured enumeration."
        },
        {
            "id": 3,
            "title": "Memory Test Across Sessions (Calibrate to PM)",
            "query": "Can you help me understand how to evaluate a machine learning model for my team?",
            "pre_func": lambda: inject_pm_profile(),
            "description": "Injects PM at health-tech startup into user_profile.json to test long-term memory calibration (lower math, focus on strategy)."
        },
        {
            "id": 4,
            "title": "The Prop Test (Neural Networks)",
            "query": "How do you think about neural network architecture?",
            "pre_func": None,
            "description": "Tests Andrew's signature Lego bricks analogy for neural networks."
        },
        {
            "id": 5,
            "title": "Disagreement Pushback",
            "query": "I think more data is always better than a better algorithm. What do you think?",
            "pre_func": None,
            "description": "Tests Socratic pushback style and references to Machine Learning Yearning content."
        },
        {
            "id": 6,
            "title": "Agentic AI Framework (Temporal Hedging)",
            "query": "What do you think about AI agents in 2026?",
            "pre_func": None,
            "description": "Tests the four agentic design patterns and temporal hedging disclaimers for post-corpus queries."
        },
        {
            "id": 7,
            "title": "Teaching a Hard Concept (Bias-Variance)",
            "query": "I keep hearing about bias-variance tradeoff but I don't really get it.",
            "pre_func": None,
            "description": "Tests dartboard target analogy, underfitting/overfitting, and diagnostic checks (train vs dev error)."
        },
        {
            "id": 8,
            "title": "Strategy Question (Project Prioritization)",
            "query": "I have 3 ideas for my ML project, how do I decide which to tackle first?",
            "pre_func": None,
            "description": "Tests ceiling analysis framework and error analysis from Machine Learning Yearning."
        },
        {
            "id": 9,
            "title": "AI Ethics and Jobs",
            "query": "Are you worried about AI taking away jobs?",
            "pre_func": None,
            "description": "Tests ethical stance (jobs disruption vs killer robots), education infrastructure solutions, and optimism."
        },
        {
            "id": 10,
            "title": "Meta-Question About Learning ML",
            "query": "What's the most common mistake beginners make when learning ML?",
            "pre_func": None,
            "description": "Tests encouraging tone, focus on building over studying, and final actionable guidance."
        }
    ]
    
    # Store session history
    chat_history = []
    
    markdown_output = []
    markdown_output.append("# Andrew Ng Digital Twin — 10 Sample Conversations")
    markdown_output.append("This document records ten representative dialogues run through the active digital twin system. It showcases the agent's persona consistency, accuracy, RAG grounding, and memory integration.\n")
    
    for scen in scenarios:
        print(f"\n--- Running Scenario {scen['id']}: {scen['title']} ---")
        
        # Run pre-function to manipulate memory state if needed
        if scen["pre_func"]:
            scen["pre_func"]()
            
        query = scen["query"]
        print(f"Query: {query}")
        
        start_time = time.time()
        res_text, citations = generate_digital_twin_response(query, chat_history=chat_history)
        elapsed = time.time() - start_time
        
        # Word count check
        words = len(res_text.split())
        print(f"Response ({words} words) in {elapsed:.2f}s:")
        print(res_text)
        
        # Add to session history
        chat_history.append({"role": "user", "content": query})
        chat_history.append({"role": "assistant", "content": res_text})
        
        # Build markdown block
        markdown_output.append(f"## Conversation {scen['id']}: {scen['title']}")
        markdown_output.append(f"**Description**: {scen['description']}\n")
        markdown_output.append(f"### 👤 Student Query")
        markdown_output.append(f"> {query}\n")
        markdown_output.append(f"### 🎓 Andrew Ng Response")
        markdown_output.append(f"{res_text}\n")
        
        if citations:
            markdown_output.append("### 📚 Grounding Citations")
            for cit in citations:
                canonical_mark = " (🔥 Canonical Analogy)" if cit.get("canonical_example") else ""
                markdown_output.append(f"- **Source**: {cit.get('source')} ({cit.get('doc_type')}) | **Title**: {cit.get('title')}{canonical_mark}")
            markdown_output.append("")
        else:
            markdown_output.append("*(No external grounding citations required for general/rapport query)*\n")
            
        markdown_output.append("--- \n")
        
        # Wait a little to let background thread save memory safely
        time.sleep(1.5)
        
    # Write conversations.md
    output_path = Path(__file__).resolve().parent.parent / "conversations.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown_output))
    print(f"\n[Success] Conversations successfully written to: {output_path}")

def inject_pm_profile():
    print("Injecting PM context into user_profile.json...")
    profile = load_user_profile()
    profile["student_profile"] = {
        "identity": "Product Manager",
        "industry_domain": "Health-Tech Startup",
        "mathematical_comfort_level": "Conceptual (Low Math)"
    }
    profile["career_and_business_goals"] = {
        "short_term": "Build a health recommendation system",
        "long_term": "Lead AI product strategy in clinical healthcare"
    }
    profile["personal_rapport"] = {
        "name": "Sarah",
        "location": "Boston",
        "notable_remarks": [
            "Sarah mentioned in the previous session that she leads product at a health-tech startup and wants to focus on strategy rather than formulas."
        ]
    }
    profile["topics_discussed_timeline"] = [
        {"topic": "Model Evaluation Intro", "date": "2026-06-01", "session": 1}
    ]
    save_user_profile(profile)
    
    # Also add an episodic memory entry
    store = load_episodic_memory_store()
    store["entries"].append({
        "memory": "Sarah is a Product Manager at a health-tech startup who prefers low-math strategy over complex mathematical equations.",
        "topic": "Student Identity",
        "memory_type": "project_context",
        "tags": ["sarah", "pm", "health-tech", "low-math"],
        "importance": 3,
        "timestamp": "2026-06-01T10:00:00",
        "source_query": "I am Sarah, a PM at a health tech startup"
    })
    save_episodic_memory_store(store)

if __name__ == "__main__":
    run_scenarios()
