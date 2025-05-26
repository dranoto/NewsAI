# app/summarizer.py
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains.summarize import load_summarize_chain
from langchain.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from . import config

def initialize_llm(api_key: str, model_name: str, temperature: float, max_output_tokens: int):
    """Generic LLM initializer."""
    if not api_key:
        raise ValueError("API key is required to initialize the LLM.")
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
        max_output_tokens=max_output_tokens
    )

def get_summarization_prompt():
    """Returns the PromptTemplate for news summarization."""
    prompt_template_text = """Please summarize the following text in English.
    Keep the summary concise (around 100-150 words) and based only on the provided text.
    If the text is empty or an error occurs, return 'Content empty'.

    Text:
    {text}

    Summary:"""
    return PromptTemplate.from_template(prompt_template_text)

async def summarize_document_content(document: Document, chain) -> str:
    """Summarizes the content of a single Langchain Document using the provided chain."""
    if not document or not document.page_content.strip():
        return "Content empty (document was empty or whitespace)."
    
    print(f"Summarizing content from: {document.metadata.get('source', 'N/A')} (Length: {len(document.page_content)})")
    try:
        result = await chain.ainvoke({"input_documents": [document]})
        return result.get("output_text", "Error: Could not extract summary from LLM output.")
    except Exception as e:
        print(f"Error during summarization for {document.metadata.get('source', 'N/A')}: {e}")
        return f"Error during summarization: {type(e).__name__} - {e}"

async def get_chat_response(chat_llm_instance: ChatGoogleGenerativeAI, article_content: str, question: str) -> str:
    """
    Gets a contextual answer from the LLM. Uses article content as primary context,
    but allows general knowledge if the question implies broader context.
    """
    if not chat_llm_instance:
        return "Error: Chat LLM not initialized."
    if not question.strip():
        return "Error: No question provided."

    print(f"Attempting chat with {chat_llm_instance.model}. Question: '{question}'")
    
    article_context_for_prompt = "No specific article content was provided with this question."
    if article_content and article_content.strip():
        max_chars = 15000 
        article_context_for_prompt = article_content[:max_chars]
        if len(article_content) > max_chars:
            article_context_for_prompt += " [Content Truncated]"
    
    system_prompt_content = f"""You are a helpful AI assistant. The user is asking a question, and they may have been reading a news article.
Here is the content of the article they were reading, if available. Use it as primary context for your answer:
---
Article Content:
{article_context_for_prompt}
---
Please answer the user's question.
- If the question can be directly and fully answered using the provided Article Content, prioritize that information in your response.
- If the question seems to require general knowledge or background context that goes beyond the provided Article Content (e.g., "Tell me more about the history of X," or "What is the significance of Y?"), you are encouraged to use your broader knowledge base to provide a comprehensive answer. You can still reference the Article Content if it's relevant to the broader topic.
- If the Article Content is provided but doesn't help answer the question, AND the question is specifically *about what the article itself contains* (e.g., "What did this article say about Z?"), then you should state that the information is not in the provided text.
- If no Article Content was provided (i.e., the Article Content above says "No specific article content was provided..."), answer the question using your general knowledge.
- Be informative, helpful, and aim for a conversational tone.
"""

    messages = [
        SystemMessage(content=system_prompt_content),
        HumanMessage(content=question),
    ]

    try:
        ai_response = await chat_llm_instance.ainvoke(messages)
        answer = ai_response.content
        print(f"LLM chat response: {answer}")
        return answer
    except Exception as e:
        print(f"Error during LLM chat interaction: {e}")
        return f"Error getting answer from AI: {type(e).__name__} - {e}"
