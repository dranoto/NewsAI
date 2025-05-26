# app/summarizer.py
from langchain_google_genai import GoogleGenerativeAI
from langchain.docstore.document import Document
from langchain.prompts import PromptTemplate
from langchain.chains.summarize import load_summarize_chain # Still used for its structure
from typing import Optional, Any
from . import config 

# --- LLM Initialization ---
def initialize_llm(api_key: str, model_name: str, temperature: float = 0.3, max_output_tokens: int = 1024):
    try:
        llm = GoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        print(f"Successfully initialized LLM: {model_name}")
        return llm
    except Exception as e:
        print(f"Error initializing LLM {model_name}: {e}")
        return None

# --- Summarization Specifics ---
def get_summarization_prompt_template(custom_prompt_str: Optional[str] = None) -> PromptTemplate:
    template_str = custom_prompt_str if custom_prompt_str and "{text}" in custom_prompt_str else config.DEFAULT_SUMMARY_PROMPT
    if custom_prompt_str and "{text}" not in custom_prompt_str:
        print(f"Warning: Custom summary prompt was provided but is missing '{{text}}' placeholder. Using default prompt.")
        
    return PromptTemplate(template=template_str, input_variables=["text"])

async def summarize_document_content(
    doc: Document, 
    llm_instance: GoogleGenerativeAI, 
    custom_prompt_str: Optional[str] = None
) -> str:
    if not llm_instance:
        return "Error: Summarization LLM not available."
    if not doc.page_content or len(doc.page_content.strip()) < 50: # Basic check
        print(f"Content too short for URL {doc.metadata.get('source', 'Unknown')}. Length: {len(doc.page_content.strip())}")
        return "Content too short or empty to summarize."

    try:
        prompt_template = get_summarization_prompt_template(custom_prompt_str)
        # The chain is useful for structuring the call, especially 'stuff' method
        chain = load_summarize_chain(llm_instance, chain_type="stuff", prompt=prompt_template)
        
        print(f"Attempting to summarize URL: {doc.metadata.get('source', 'Unknown URL')} with prompt: \"{prompt_template.template[:100]}...\"")
        # For 'stuff' chain, the input is a list of documents, but here we only have one.
        # The chain internally extracts page_content.
        # The `ainvoke` method for chains typically expects a dictionary matching the chain's input keys.
        # For `load_summarize_chain`, the input key is often 'input_documents'.
        # However, we are passing a single document's content to a prompt that expects "text".
        # Let's try invoking the llm_chain part of the summarize_chain directly if it's simpler,
        # or ensure the input to ainvoke is what the specific chain expects.
        # The 'stuff' chain's llm_chain takes 'text' as input.

        # If using chain.ainvoke, the input should match the chain's expected input_keys.
        # For a StuffDocumentsChain, it's typically `{"input_documents": [doc]}`.
        # The result is often a dict like `{"output_text": "summary..."}`.
        
        # Let's simplify and use the LLM directly with the formatted prompt if `load_summarize_chain` is tricky with `ainvoke` for single docs
        # formatted_prompt_value = await prompt_template.aformat(text=doc.page_content)
        # summary_output = await llm_instance.ainvoke(formatted_prompt_value)
        # summary = summary_output if isinstance(summary_output, str) else getattr(summary_output, 'text', str(summary_output))

        # Using the chain's `ainvoke` method:
        # The StuffDocumentsChain expects a list of documents under the key "input_documents"
        result = await chain.ainvoke({"input_documents": [doc]})
        summary = result.get("output_text", "").strip() # Default to empty string if key not found

        if not summary:
            print(f"Empty summary received from LLM for URL: {doc.metadata.get('source', 'Unknown URL')}")
            return "Error: Summary generation resulted in empty output."
        
        print(f"Successfully summarized URL: {doc.metadata.get('source', 'Unknown URL')}. Summary length: {len(summary)}")
        return summary
    except Exception as e:
        print(f"ERROR during summarization for doc '{doc.metadata.get('source', 'Unknown URL')}': {e}")
        # import traceback
        # traceback.print_exc() # For more detailed error
        return f"Error generating summary: {str(e)}"


# --- Chat Specifics ---
async def get_chat_response(
    llm_instance: GoogleGenerativeAI, 
    article_text: str, 
    question: str,
    custom_chat_prompt_str: Optional[str] = None
) -> str:
    # ... (This function seems okay, but ensure llm_instance.ainvoke is used correctly) ...
    # The existing get_chat_response already uses llm_instance.ainvoke(formatted_prompt)
    # which is the correct modern way for a direct LLM call.
    # We'll keep it as is but ensure logging is good.
    if not llm_instance:
        return "Error: Chat LLM not available."

    final_prompt_str: str
    input_variables = ["question"] # Default

    if not article_text or len(article_text.strip()) < 20:
        final_prompt_str = custom_chat_prompt_str if custom_chat_prompt_str and "{question}" in custom_chat_prompt_str else config.CHAT_NO_ARTICLE_PROMPT
        if "{question}" not in final_prompt_str:
             final_prompt_str = "I'm sorry, but the article content could not be loaded, so I cannot answer your question about it."
             prompt = PromptTemplate(template=final_prompt_str, input_variables=[])
             formatted_prompt = prompt.format()
        else:
            prompt = PromptTemplate(template=final_prompt_str, input_variables=["question"])
            formatted_prompt = prompt.format(question=question)
    else: 
        if custom_chat_prompt_str:
            final_prompt_str = custom_chat_prompt_str
            if "{article_text}" in final_prompt_str and "{question}" in final_prompt_str:
                input_variables = ["article_text", "question"]
            elif "{question}" in final_prompt_str:
                input_variables = ["question"] # Might ignore article_text
            else: 
                print("Warning: Custom chat prompt is missing required placeholders. Using default.")
                final_prompt_str = config.DEFAULT_CHAT_PROMPT
                input_variables = ["article_text", "question"]
        else:
            final_prompt_str = config.DEFAULT_CHAT_PROMPT
            input_variables = ["article_text", "question"]

        try:
            prompt = PromptTemplate(template=final_prompt_str, input_variables=input_variables)
            if "article_text" in input_variables and "question" in input_variables:
                formatted_prompt = prompt.format(article_text=article_text, question=question)
            elif "question" in input_variables:
                formatted_prompt = prompt.format(question=question)
            else: 
                formatted_prompt = final_prompt_str 
        except Exception as e:
            print(f"Error formatting chat prompt: {e}. Using raw prompt string.")
            formatted_prompt = f"Article: {article_text}\nQuestion: {question}" # Basic fallback

    print(f"Attempting chat with prompt: \"{formatted_prompt[:150]}...\"")
    try:
        response_obj = await llm_instance.ainvoke(formatted_prompt)
        answer = response_obj if isinstance(response_obj, str) else getattr(response_obj, 'text', str(response_obj))
        if not answer.strip():
            print("Empty answer received from chat LLM.")
            return "AI returned an empty answer."
        print(f"Chat LLM returned answer length: {len(answer)}")
        return answer.strip()
    except Exception as e:
        print(f"ERROR getting answer from AI for chat: {e}")
        # import traceback
        # traceback.print_exc()
        return f"Error getting answer from AI: {str(e)}"

