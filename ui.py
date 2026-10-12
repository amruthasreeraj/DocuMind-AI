
import os
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="DocuMind AI",
    page_icon="🧠",
    layout="wide"
)

# Custom styling
st.markdown("""
<style>
    .block-container {
        max-width: 1100px;
        padding-top: 2rem;
    }

    h1, h2, h3 {
        letter-spacing: -0.5px;
    }

    div.stButton > button {
        border-radius: 10px;
        font-weight: 600;
    }

    [data-testid="stSidebar"] {
        background-color: #F4F6FA;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.title("🧠 DocuMind AI")
st.caption("Intelligent Document Assistant | Powered by RAG")
st.divider()

# Sidebar — PDF upload
with st.sidebar:
    st.header("📁 Knowledge Base")
    st.write("Upload PDF documents to make them searchable.")

    uploaded_file = st.file_uploader(
        "Choose a PDF",
        type=["pdf"]
    )

    if st.button("Upload Document", use_container_width=True):
        if uploaded_file is None:
            st.warning("Please select a PDF first.")
        else:
            try:
                with st.spinner("Indexing document..."):
                    response = requests.post(
                        f"{API_URL}/upload",
                        files={
                            "file": (
                                uploaded_file.name,
                                uploaded_file.getvalue(),
                                "application/pdf"
                            )
                        },
                        timeout=180
                    )

                response.raise_for_status()
                result = response.json()

                st.success(result["message"])
                st.caption(
                    f"Chunks indexed: {result['chunks_indexed']}"
                )

            except requests.RequestException as e:
                st.error(f"Upload failed: {e}")

    st.divider()
    st.caption("FastAPI • LangChain • ChromaDB • Ollama")

# Main area
st.subheader("💬 Ask Your Documents")
st.write(
    "Ask questions about your uploaded PDFs and receive "
    "AI-generated answers with source references."
)

question = st.text_input(
    "Your question",
    placeholder="e.g. What is the remote work policy?"
)

if st.button("✨ Generate Answer", type="primary"):
    if not question.strip():
        st.warning("Please enter a question.")
    else:
        try:
            with st.spinner("Searching documents and generating answer..."):
                response = requests.post(
                    f"{API_URL}/ask",
                    json={"question": question},
                    timeout=180
                )

            response.raise_for_status()
            result = response.json()

            st.session_state["last_result"] = result

        except requests.RequestException as e:
            st.error(f"Request failed: {e}")

# Display latest answer
if "last_result" in st.session_state:
    result = st.session_state["last_result"]

    st.divider()
    st.markdown("### ✨ AI Answer")
    st.info(result["answer"])

    sources = result.get("sources", [])

    if sources:
        st.markdown("### 📚 Retrieved Sources")

        for source in sources:
            with st.container(border=True):
                st.write(
                    f"📄 **{source['file']}** — Page {source['page']}"
                )

st.divider()
st.caption(
    "DocuMind AI • Retrieval-Augmented Generation • "
    "Answers should be verified against original documents."
)
