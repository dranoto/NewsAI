# app/summarizer.py
from langchain_google_genai import GoogleGenerativeAI
from langchain.docstore.document import Document
from langchain.prompts import PromptTemplate
from langchain.chains.summarize import load_summarize_chain # Still used for its structure
from typing import Optional, Any, List
from . import config

# --- LLM Initialization ---
def initialize_llm(api_key: str, model_name: str, temperature: float = 0.3, max_output_tokens: int = 1024):
    """
    Initializes a GoogleGenerativeAI LLM instance.
    """
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
    """
    Returns the PromptTemplate for summarization.
    Uses custom_prompt_str if provided and valid, otherwise defaults to config.DEFAULT_SUMMARY_PROMPT.
    """
    template_str = custom_prompt_str if custom_prompt_str and "{text}" in custom_prompt_str else config.DEFAULT_SUMMARY_PROMPT
    if custom_prompt_str and "{text}" not in custom_prompt_str:
        print(f"Warning: Custom summary prompt was provided but is missing '{{text}}' placeholder. Using default prompt.")
        
    return PromptTemplate(template=template_str, input_variables=["text"])

async def summarize_document_content(
    doc: Document,
    llm_instance: GoogleGenerativeAI,
    custom_prompt_str: Optional[str] = None
) -> str:
    """
    Summarizes the content of a Document using the provided LLM instance.
    """
    if not llm_instance:
        return "Error: Summarization LLM not available."
    if not doc.page_content or len(doc.page_content.strip()) < 50: # Basic check
        print(f"Content too short for URL {doc.metadata.get('source', 'Unknown')}. Length: {len(doc.page_content.strip())}")
        return "Content too short or empty to summarize."

    try:
        prompt_template = get_summarization_prompt_template(custom_prompt_str)
        chain = load_summarize_chain(llm_instance, chain_type="stuff", prompt=prompt_template)
        
        print(f"Attempting to summarize URL: {doc.metadata.get('source', 'Unknown URL')} with prompt: \"{prompt_template.template[:100]}...\"")
        
        result = await chain.ainvoke({"input_documents": [doc]})
        summary = result.get("output_text", "").strip()

        if not summary:
            print(f"Empty summary received from LLM for URL: {doc.metadata.get('source', 'Unknown URL')}")
            return "Error: Summary generation resulted in empty output."
        
        print(f"Successfully summarized URL: {doc.metadata.get('source', 'Unknown URL')}. Summary length: {len(summary)}")
        return summary
    except Exception as e:
        print(f"ERROR during summarization for doc '{doc.metadata.get('source', 'Unknown URL')}': {e}")
        return f"Error generating summary: {str(e)}"

# --- Tag Generation Specifics ---
def get_tag_generation_prompt_template(custom_prompt_str: Optional[str] = None) -> PromptTemplate:
    """
    Returns the PromptTemplate for tag generation.
    Uses custom_prompt_str if provided and valid, otherwise defaults to config.DEFAULT_TAG_GENERATION_PROMPT.
    """
    template_str = custom_prompt_str if custom_prompt_str and "{text}" in custom_prompt_str else config.DEFAULT_TAG_GENERATION_PROMPT
    if custom_prompt_str and "{text}" not in custom_prompt_str:
        print(f"Warning: Custom tag generation prompt was provided but is missing '{{text}}' placeholder. Using default prompt.")
    return PromptTemplate(template=template_str, input_variables=["text"])

async def generate_tags_for_text(
    text_content: str,
    llm_instance: GoogleGenerativeAI,
    custom_prompt_str: Optional[str] = None
) -> List[str]:
    """
    Generates a list of tags for the given text_content using the provided LLM instance.
    """
    if not llm_instance:
        print("Error: Tag generation LLM not available.")
        return []
    if not text_content or len(text_content.strip()) < 20: # Basic check for meaningful content
        print(f"Content too short for tag generation. Length: {len(text_content.strip())}")
        return []

    try:
        prompt_template = get_tag_generation_prompt_template(custom_prompt_str)
        formatted_prompt = await prompt_template.aformat(text=text_content)
        
        print(f"Attempting to generate tags with prompt: \"{formatted_prompt[:150]}...\"")
        
        response_obj = await llm_instance.ainvoke(formatted_prompt)
        tags_string = response_obj if isinstance(response_obj, str) else getattr(response_obj, 'text', str(response_obj))

        if not tags_string.strip():
            print("Empty tag string received from LLM.")
            return []

        # Parse the comma-separated string into a list of tags
        # Clean up whitespace and filter out empty tags
        tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        print(f"Successfully generated tags: {tags_list}. Raw string: '{tags_string}'")
        return tags_list
    except Exception as e:
        print(f"ERROR during tag generation: {e}")
        return []


# --- Chat Specifics ---
async def get_chat_response(
    llm_instance: GoogleGenerativeAI,
    article_text: str,
    question: str,
    custom_chat_prompt_str: Optional[str] = None
) -> str:
    """
    Generates a chat response based on article text and a question using the LLM.
    """
    if not llm_instance:
        return "Error: Chat LLM not available."

    final_prompt_str: str
    input_variables = ["question"] # Default

    if not article_text or len(article_text.strip()) < 20:
        # Use a prompt designed for when there's no article context
        final_prompt_str = custom_chat_prompt_str if custom_chat_prompt_str and "{question}" in custom_chat_prompt_str else config.CHAT_NO_ARTICLE_PROMPT
        if "{question}" not in final_prompt_str:
             # Fallback if the no-article prompt is also misconfigured
             final_prompt_str = "I'm sorry, but the article content could not be loaded, so I cannot answer your question about it."
             prompt = PromptTemplate(template=final_prompt_str, input_variables=[])
             formatted_prompt = prompt.format() # No variables needed
        else:
            prompt = PromptTemplate(template=final_prompt_str, input_variables=["question"])
            formatted_prompt = prompt.format(question=question)
    else:
        # Use a prompt that incorporates article text
        if custom_chat_prompt_str:
            final_prompt_str = custom_chat_prompt_str
            # Determine necessary input variables based on placeholders in the custom prompt
            if "{article_text}" in final_prompt_str and "{question}" in final_prompt_str:
                input_variables = ["article_text", "question"]
            elif "{question}" in final_prompt_str: # Allows prompts that might only use the question
                input_variables = ["question"]
            else: # Fallback if custom prompt is missing essential placeholders
                print("Warning: Custom chat prompt is missing required placeholders ({article_text} and/or {question}). Using default.")
                final_prompt_str = config.DEFAULT_CHAT_PROMPT
                input_variables = ["article_text", "question"]
        else: # Default case
            final_prompt_str = config.DEFAULT_CHAT_PROMPT
            input_variables = ["article_text", "question"]

        try:
            prompt = PromptTemplate(template=final_prompt_str, input_variables=input_variables)
            # Format the prompt based on the determined input variables
            if "article_text" in input_variables and "question" in input_variables:
                formatted_prompt = prompt.format(article_text=article_text, question=question)
            elif "question" in input_variables: # Handles case where article_text might not be in the prompt
                formatted_prompt = prompt.format(question=question)
            else: # Should not happen if logic above is correct, but as a fallback
                formatted_prompt = final_prompt_str
        except Exception as e:
            print(f"Error formatting chat prompt: {e}. Using basic fallback prompt.")
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
        return f"Error getting answer from AI: {str(e)}"
