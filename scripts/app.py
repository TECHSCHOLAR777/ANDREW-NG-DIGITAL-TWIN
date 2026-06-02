import streamlit as st
import time
import uuid
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Import our custom persona engine
from persona_engine import (
    generate_digital_twin_response, 
    load_user_profile, 
    reset_user_profile, 
    load_episodic_memory_store,
    preload_resources,
)

# Load environment variables
load_dotenv()

# ================================================================================
# Page Configuration & Aesthetics
# ================================================================================
st.set_page_config(
    page_title="Andrew Ng Digital Twin - RAG Companion",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Premium dark theme styling with glassmorphism cards and smooth animations
st.markdown("""
<style>
    /* Main Background with Radial Gradient */
    .stApp {
        background: radial-gradient(circle at top right, #1E1B4B, #0F172A 70%) !important;
        color: #E2E8F0 !important;
        font-family: 'Inter', system-ui, sans-serif !important;
    }
    
    /* Header Styling */
    .app-header {
        font-weight: 800;
        font-size: 2.2rem;
        background: linear-gradient(90deg, #38BDF8, #818CF8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2px;
        letter-spacing: -0.5px;
    }
    
    .timeline-badge {
        display: inline-block;
        background-color: rgba(56, 189, 248, 0.12);
        color: #38BDF8;
        border: 1px solid rgba(56, 189, 248, 0.25);
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-bottom: 25px;
    }

    /* Glassmorphism Containers & Cards */
    .glass-card {
        background: rgba(30, 41, 59, 0.45);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 10px 30px 0 rgba(0, 0, 0, 0.25);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    
    .glass-card:hover {
        transform: translateY(-2px);
        border-color: rgba(129, 140, 248, 0.25);
    }
    
    .glass-card-title {
        font-weight: 700;
        font-size: 0.9rem;
        margin-bottom: 8px;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    
    .glass-card-content {
        font-size: 0.88rem;
        color: #94A3B8;
        line-height: 1.5;
    }
    
    /* Scrollbars */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: rgba(15, 23, 42, 0.3);
    }
    ::-webkit-scrollbar-thumb {
        background: rgba(129, 140, 248, 0.3);
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: rgba(129, 140, 248, 0.5);
    }
    
    /* Welcome Card */
    .welcome-card {
        background: rgba(30, 41, 59, 0.35);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 16px;
        padding: 30px;
        margin-bottom: 20px;
        line-height: 1.6;
    }
    
    .welcome-card h2 {
        background: linear-gradient(90deg, #38BDF8, #818CF8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        margin-top: 0;
    }
    
    .welcome-card ul {
        margin-top: 10px;
        padding-left: 20px;
        color: #94A3B8;
    }

    /* Citation Badges */
    .citation-badge {
        display: inline-block;
        background-color: rgba(30, 41, 59, 0.6);
        color: #94A3B8;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 6px;
        padding: 3px 10px;
        font-size: 0.78rem;
        margin-right: 6px;
        margin-top: 6px;
        text-decoration: none;
        transition: all 0.2s;
    }
    
    .citation-badge:hover {
        background-color: rgba(129, 140, 248, 0.15);
        color: #E2E8F0;
        border-color: rgba(129, 140, 248, 0.3);
    }

    /* Streamlit Chat Element Custom Overrides */
    [data-testid="stChatMessage"] {
        background-color: rgba(30, 41, 59, 0.25) !important;
        backdrop-filter: blur(8px) !important;
        -webkit-backdrop-filter: blur(8px) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 12px !important;
        padding: 18px !important;
        margin-bottom: 15px !important;
        box-shadow: 0 4px 15px 0 rgba(0, 0, 0, 0.15) !important;
    }

    [data-testid="stChatMessageUser"] {
        background-color: rgba(129, 140, 248, 0.08) !important;
        border: 1px solid rgba(129, 140, 248, 0.18) !important;
    }
    
    .sidebar-header {
        font-size: 1.2rem;
        font-weight: 800;
        color: #38BDF8;
        margin-bottom: 15px;
        padding-bottom: 5px;
        border-bottom: 1px solid rgba(56, 189, 248, 0.2);
    }
    
    /* Loading screen */
    .loading-screen {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 60vh;
        text-align: center;
        padding: 40px;
    }
    
    .loading-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #38BDF8, #818CF8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 15px;
        animation: pulse-glow 2s infinite ease-in-out;
    }
    
    @keyframes pulse-glow {
        0%, 100% { opacity: 0.8; }
        50% { opacity: 1; transform: scale(1.02); }
    }
    
    .loading-text {
        font-size: 1.05rem;
        color: #94A3B8;
        max-width: 500px;
        line-height: 1.6;
        margin-bottom: 30px;
    }
</style>
""", unsafe_allow_html=True)

# ================================================================================
# SESSION MANAGEMENT (Local Filesystem Storage)
# ================================================================================
SESSION_DIR = Path("data/sessions")
SESSION_DIR.mkdir(parents=True, exist_ok=True)

def list_sessions() -> list[dict]:
    """Lists all available chat sessions ordered by updated_at desc."""
    sessions = []
    for f in SESSION_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
                if "session_id" in data:
                    sessions.append(data)
        except Exception:
            pass
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions

def save_session(session_id: str, title: str, messages: list):
    """Saves the current session history and metadata to data/sessions/."""
    filepath = SESSION_DIR / f"{session_id}.json"
    created_at = datetime.utcnow().isoformat()
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                created_at = old_data.get("created_at", created_at)
        except Exception:
            pass
            
    data = {
        "session_id": session_id,
        "title": title,
        "created_at": created_at,
        "updated_at": datetime.utcnow().isoformat(),
        "messages": messages
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def delete_session_file(session_id: str):
    """Deletes a session file from storage."""
    filepath = SESSION_DIR / f"{session_id}.json"
    if filepath.exists():
        filepath.unlink()

# ================================================================================
# PRELOAD ROUTINE (Loading screen prior to first interaction)
# ================================================================================
if "initialized" not in st.session_state:
    st.markdown("""
    <div class="loading-screen">
        <div class="loading-title">🎓 Setting Up Andrew Ng Digital Twin</div>
        <div class="loading-text">
            Please wait while we initialize the vector database, build the BM25 keyword index, 
            and load the neural embedding & cross-encoder models into memory. 
            This ensures minimum conversation latency.
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    with st.spinner("🚀 Loading AI models & indexing grounding corpus..."):
        preload_resources()
        st.session_state.initialized = True
        
    st.success("All systems operational! Launching interface...")
    time.sleep(1.0)
    st.rerun()

# Initialize standard state
if "sessions" not in st.session_state:
    st.session_state.sessions = list_sessions()

# Ensure active session is set
if "current_session_id" not in st.session_state or not st.session_state.current_session_id:
    if st.session_state.sessions:
        most_recent = st.session_state.sessions[0]
        st.session_state.current_session_id = most_recent["session_id"]
        st.session_state.session_title = most_recent["title"]
        st.session_state.messages = most_recent.get("messages", [])
    else:
        new_id = str(uuid.uuid4())
        st.session_state.current_session_id = new_id
        st.session_state.session_title = "New Chat"
        st.session_state.messages = []
        save_session(new_id, "New Chat", [])
        st.session_state.sessions = list_sessions()

# ================================================================================
# SIDEBAR NAVIGATION (Session Manager)
# ================================================================================
with st.sidebar:
    st.markdown('<div class="sidebar-header">💬 Chat Sessions</div>', unsafe_allow_html=True)
    
    # New Chat Button
    if st.button("➕ New Chat", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.current_session_id = new_id
        st.session_state.session_title = "New Chat"
        st.session_state.messages = []
        save_session(new_id, "New Chat", [])
        st.session_state.sessions = list_sessions()
        st.query_params.clear()
        st.rerun()
        
    st.markdown("")
    
    # Render List of Past Sessions with active styling and delete controls
    for session in st.session_state.sessions:
        s_id = session["session_id"]
        s_title = session["title"]
        
        # Truncate title for sidebar
        disp_title = s_title[:24] + "..." if len(s_title) > 24 else s_title
        
        cols = st.columns([5, 1])
        
        # Session Select Button
        is_active = (s_id == st.session_state.current_session_id)
        btn_label = f"👉 {disp_title}" if is_active else f"📄 {disp_title}"
        
        if cols[0].button(btn_label, key=f"btn_sel_{s_id}", use_container_width=True):
            st.session_state.current_session_id = s_id
            st.session_state.session_title = s_title
            st.session_state.messages = session.get("messages", [])
            st.query_params.clear()
            st.rerun()
            
        # Session Delete Button
        if cols[1].button("🗑️", key=f"btn_del_{s_id}"):
            delete_session_file(s_id)
            st.session_state.sessions = list_sessions()
            if st.session_state.current_session_id == s_id:
                st.session_state.current_session_id = None
            st.rerun()
            
    st.markdown("<br/><br/>", unsafe_allow_html=True)
    
    # Global memory reset at bottom of sidebar
    if st.button("🗑️ Reset All Memory Contexts", use_container_width=True):
        reset_user_profile()
        st.success("Student profile and long-term memory reset successfully!")
        time.sleep(1.0)
        st.rerun()

# ================================================================================
# MAIN SCREEN INTERFACE
# ================================================================================

# Title banner across main area
st.markdown('<h1 class="app-header">🎓 Andrew Ng Digital Twin</h1>', unsafe_allow_html=True)
st.markdown('<span class="timeline-badge">🧠 Brain Grounded: 1.71 Million Words (2000-2026) • Gemini 2.5 Flash</span>', unsafe_allow_html=True)

# Split main workspace into interactive chat/voice column and live memory inspector column
main_col, memory_col = st.columns([3, 1])

# --------------------------------------------------------------------------------
# COLUMN 1: Dialogue & Interaction
# --------------------------------------------------------------------------------
with main_col:
    st.markdown("<p style='font-size:0.9rem; font-weight:700; color:#818CF8; margin-top:0px; margin-bottom:10px;'>💬 DIALOGUE RUNTIME</p>", unsafe_allow_html=True)
    
    # Display welcome card if chat history is empty
    if not st.session_state.messages:
        st.markdown("""
        <div class="welcome-card">
            <h2>Welcome to Andrew's Classroom!</h2>
            <p>Hello! I am <b>Andrew Ng</b>. 
            I teach using my CS229 lecture notes, Machine Learning Yearning chapters, and issues of The Batch.</p>
            <p>Feel free to ask me anything about Machine Learning theory, Deep Learning architectures, AI Strategy, or career planning.</p>
        </div>
        """, unsafe_allow_html=True)
        
    # Display conversation history list
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
            # Render citation badges for assistant responses
            if msg["role"] == "assistant" and "citations" in msg:
                citations = msg["citations"]
                if citations:
                    st.markdown("<div style='margin-top: 8px;'>", unsafe_allow_html=True)
                    for cit in citations:
                        title_trunc = cit.get('title', 'Grounding Source')
                        if len(title_trunc) > 30:
                            title_trunc = title_trunc[:27] + "..."
                            
                        badge_style = "border-color: #EF4444; color: #EF4444; background: rgba(239, 68, 68, 0.04);" if cit.get('canonical_example') else ""
                        canonical_text = " [🔥 Analogy]" if cit.get('canonical_example') else ""
                        
                        st.markdown(
                            f"<span class='citation-badge' style='{badge_style}' title='Source: {cit.get('source')} | Domain: {cit.get('domain')}'>{title_trunc}{canonical_text}</span>",
                            unsafe_allow_html=True
                        )
                    st.markdown("</div>", unsafe_allow_html=True)

    # Standard User Text Input
    user_input = st.chat_input("Ask Andrew a question about ML theory, career strategy, or AI trends...")
    
    if user_input:
        # Append User Turn
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)
            
        # Update title dynamically on first query
        title = st.session_state.session_title
        if title == "New Chat":
            title = user_input[:30] + "..." if len(user_input) > 30 else user_input
            st.session_state.session_title = title
            
        # Generate Assistant Turn
        with st.chat_message("assistant"):
            with st.spinner("Andrew is formulating an explanation..."):
                response_text, citations = generate_digital_twin_response(
                    user_input, 
                    chat_history=st.session_state.messages[:-1]
                )
                st.write(response_text)
                
                # Display citations
                if citations:
                    st.markdown("<div style='margin-top: 8px;'>", unsafe_allow_html=True)
                    for cit in citations:
                        title_trunc = cit.get('title', 'Grounding Source')
                        if len(title_trunc) > 30:
                            title_trunc = title_trunc[:27] + "..."
                            
                        badge_style = "border-color: #EF4444; color: #EF4444; background: rgba(239, 68, 68, 0.04);" if cit.get('canonical_example') else ""
                        canonical_text = " [🔥 Analogy]" if cit.get('canonical_example') else ""
                        
                        st.markdown(
                            f"<span class='citation-badge' style='{badge_style}' title='Source: {cit.get('source')} | Domain: {cit.get('domain')}'>{title_trunc}{canonical_text}</span>",
                            unsafe_allow_html=True
                        )
                    st.markdown("</div>", unsafe_allow_html=True)
                    
        # Append Assistant Turn to history
        st.session_state.messages.append({
            "role": "assistant", 
            "content": response_text,
            "citations": citations
        })
        
        # Save session back to storage
        save_session(
            st.session_state.current_session_id, 
            st.session_state.session_title, 
            st.session_state.messages
        )
        
        st.session_state.sessions = list_sessions()
        st.rerun()

# --------------------------------------------------------------------------------
# COLUMN 2: Memory Dashboard / Inspector
# --------------------------------------------------------------------------------
with memory_col:
    st.markdown('<p style="font-size:0.9rem; font-weight:700; color:#38BDF8; margin-top:0px; margin-bottom:10px;">🧠 MEMORY INSPECTOR</p>', unsafe_allow_html=True)
    
    # Load user profile data
    profile = load_user_profile()
    episodic_store = load_episodic_memory_store()
    episodic_entries = episodic_store.get("entries", [])
    
    # Card 1: Student Identity
    sp = profile.get("student_profile", {})
    st.markdown(f"""
    <div class="glass-card" style="border-left: 4px solid #38BDF8;">
        <div class="glass-card-title" style="color: #38BDF8;">🎓 Student Identity</div>
        <div class="glass-card-content">
            <b>Role:</b> {sp.get('identity', 'analyzing...')}<br/>
            <b>Domain:</b> {sp.get('industry_domain', 'analyzing...')}<br/>
            <b>Math Comfort:</b> {sp.get('mathematical_comfort_level', 'analyzing...')}
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Card 2: Strategic Ambitions
    goals = profile.get("career_and_business_goals", {})
    st.markdown(f"""
    <div class="glass-card" style="border-left: 4px solid #818CF8;">
        <div class="glass-card-title" style="color: #818CF8;">🎯 Strategic Ambitions</div>
        <div class="glass-card-content">
            <b>Short-Term:</b> {goals.get('short_term', 'analyzing...')}<br/>
            <b>Long-Term:</b> {goals.get('long_term', 'analyzing...')}
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Card 3: Focus Areas (Struggles & Misconceptions)
    misconceptions = profile.get("misconceptions_and_focus_areas", [])
    mis_content = "<br/>".join(f"• {m}" for m in misconceptions) if misconceptions else "No concept friction logged yet."
    st.markdown(f"""
    <div class="glass-card" style="border-left: 4px solid #EF4444;">
        <div class="glass-card-title" style="color: #EF4444;">💡 Focus Areas</div>
        <div class="glass-card-content">
            {mis_content}
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Card 4: Rapport / Personal Prefs
    rapport = profile.get("personal_rapport", {})
    notables = rapport.get("notable_remarks", [])
    notables_content = "<br/>".join(f"• {n}" for n in notables) if notables else "Interactions detail learning preference..."
    st.markdown(f"""
    <div class="glass-card" style="border-left: 4px solid #10B981;">
        <div class="glass-card-title" style="color: #10B981;">🤝 Rapport details</div>
        <div class="glass-card-content">
            <b>Name:</b> {rapport.get('name', 'unknown')}<br/>
            <b>Location:</b> {rapport.get('location', 'unknown')}<br/>
            {notables_content}
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Card 5: Long-Term Episodic Recall
    recent_memory_lines = [
        f"• {entry.get('memory')}"
        for entry in episodic_entries[:4]
        if entry.get("memory")
    ]
    recent_memory_content = "<br/>".join(recent_memory_lines) if recent_memory_lines else "No durable memories stored yet."
    st.markdown(f"""
    <div class="glass-card" style="border-left: 4px solid #F59E0B;">
        <div class="glass-card-title" style="color: #F59E0B;">🧠 Cross-Session Recall</div>
        <div class="glass-card-content">
            <b>Stored Memories:</b> {len(episodic_entries)}<br/>
            {recent_memory_content}
        </div>
    </div>
    """, unsafe_allow_html=True)
