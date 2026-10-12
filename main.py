from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
import logging
import tempfile
import hashlib


logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434"
)

LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "llama3.2:3b"
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "nomic-embed-text"
)

TOP_K = int(os.getenv(          # <- this in init because,Environment variables are normally read as strings so init() converts it to an integer. This is important because the retriever expects an integer value for the number of documents to retrieve.
    "TOP_K",
    "3"
))

app = FastAPI()


# -------------------------
# Request structure
# -------------------------

class QuestionRequest(BaseModel):
    question: str



# -------------------------
# Embeddings
# -------------------------

embeddings = OllamaEmbeddings(
    model=EMBEDDING_MODEL,
    base_url=OLLAMA_BASE_URL
)



vectorstore = Chroma(                   #Chroma(...) opens the stored collection without re-embedding the PDF.
    persist_directory="./chroma_db",
    embedding_function=embeddings,
    collection_name="maintenance_manual"
)
# -------------------------
# Retriever an interface to seach chroma to fetch 3 relevant chunks, retriver itsldef is nor having 3 hunks
# -------------------------

retriever = vectorstore.as_retriever(
    search_kwargs={"k": TOP_K}
)


# -------------------------
# LLM
# -------------------------

llm = ChatOllama(
    model=LLM_MODEL,
    base_url=OLLAMA_BASE_URL
)


# -------------------------
# Prompt
# -------------------------

prompt = ChatPromptTemplate.from_template(
   """
You are a technical document assistant.

Answer the user's question using ONLY the provided context.

Rules:
1. Use information explicitly stated in the context.
2. Do not invent machine names, specifications, or procedures.
3. If the context contains the answer, provide it clearly and directly.
4. If the context does not contain enough information, say:
   "I could not find this information in the uploaded documents."
5. Keep your answer concise.

Context:
{context}

Question:
{question}

Answer:
"""
    
)


chain = prompt | llm



def format_docs(docs):
    formatted_chunks = []

    for doc in docs:
        source = doc.metadata.get("source", "Unknown")
        page = doc.metadata.get("page_label", "Unknown")
        title = doc.metadata.get("document_title", source)

        formatted_chunks.append(
            f"Document: {title}\n"
            f"Source: {source}\n"
            f"Page: {page}\n"
            f"Content:\n{doc.page_content}"
        )

    return "\n\n---\n\n".join(formatted_chunks)

def extract_document_title(documents, filename):
    if not documents:
        return filename

    first_page = documents[0].page_content

    for line in first_page.splitlines():
        title = line.strip()

        if title:
            return title[:150]

    return filename

# -------------------------
# API endpoints
# -------------------------

@app.get("/")
def home():
    return {"message": "RAG API is running"}



@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed."
        )

    temp_path = None

    try:
        # 1. Read uploaded file
        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()

        existing = vectorstore.get(
            where={"file_hash": file_hash},
            limit=1
        )

        if existing["ids"]:
            return {
                "filename": file.filename,
                "message": "This PDF has already been indexed.",
                "chunks_indexed": 0
            }
        if not content.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail="Invalid PDF file."
            )

        # 2. Save temporarily so PyPDFLoader can read it
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pdf"
        ) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name

        # 3. Load PDF
        loader = PyPDFLoader(temp_path)
        documents = loader.load()

        if not documents:
            raise HTTPException(
                status_code=400,
                detail="No readable pages found."
            )
        
        document_title = extract_document_title(documents, file.filename)

        logger.info("Extracted document title: %s", document_title)

        # Keep the original filename in metadata
        for doc in documents:
            doc.metadata["source"] = os.path.basename(file.filename)

        # 4. Split into chunks
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100
        )

        chunks = splitter.split_documents(documents)
        for chunk in chunks:
            chunk.metadata["file_hash"] = file_hash

        if not chunks:
            raise HTTPException(
                status_code=400,
                detail="No readable text found."
            )

        # 5. Generate embeddings and store in Chroma
        vectorstore.add_documents(chunks)

        logger.info("Indexed %d uploaded chunks", len(chunks))

        return {
            "filename": file.filename,
            "chunks_indexed": len(chunks),
            "message": "Document indexed successfully."
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Document upload failed")
        raise HTTPException(
            status_code=500,
            detail="Document processing failed."
        )

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        await file.close()


@app.post("/ask")
def ask_question(request: QuestionRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )
    try:
        
        logger.info("Received a question")

        retrieved_docs = retriever.invoke(question)
        for doc in retrieved_docs:
            print("Content:", doc.page_content[:100])
            print("Metadata:", doc.metadata)
            print("--------------------")
        
        logger.info(
            "Retrieved %d documents",
            len(retrieved_docs)
        )

        context = format_docs(retrieved_docs)
        logger.info("Context sent to LLM:\n%s", context)

        response = chain.invoke({
            "context": context,
            "question": question
        })

        sources = []

        for doc in retrieved_docs:
            source = {
                "file": doc.metadata.get("source", "Unknown"),
                "page": doc.metadata.get(
                    "page_label",
                    doc.metadata.get("page", 0) + 1
                )
            }

            if source not in sources:
                sources.append(source)

        logger.info("Generated RAG response")


        return {
            "question": question,
            "answer": response.content,            "sources": sources
        }
    except Exception as e:
        logger.exception("RAG request failed")

        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing the question."
        )