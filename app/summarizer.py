# app/summarizer.py
from langchain_google_genai import GoogleGenerativeAI
from langchain.docstore.document import Document
from langchain.prompts import PromptTemplate
from langchain.chains.summarize import load_summarize_chain
from typing import Optional, Any, List, Dict
from . import config
import logging

# Ensure BeautifulSoup is imported if you choose to use HTML to text conversion
# from bs4 import BeautifulSoup # Uncomment if using HTML to text conversion

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- LLM Initialization --- (assuming this remains the same)
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
        logger.info(f"Successfully initialized LLM: {model_name} with max_output_tokens: {max_output_tokens}")
        return llm
    except Exception as e:
        logger.error(f"Error initializing LLM {model_name}: {e}")
        return None

# --- Summarization Specifics --- (assuming get_summarization_prompt_template remains the same)
def get_summarization_prompt_template(custom_prompt_str: Optional[str] = None) -> PromptTemplate:
    """
    Returns the PromptTemplate for summarization.
    Uses custom_prompt_str if provided and valid, otherwise defaults to config.DEFAULT_SUMMARY_PROMPT.
    """
    template_str = custom_prompt_str if custom_prompt_str and "{text}" in custom_prompt_str else config.DEFAULT_SUMMARY_PROMPT
    if custom_prompt_str and "{text}" not in custom_prompt_str:
        logger.warning(f"Custom summary prompt was provided but is missing '{{text}}' placeholder. Using default prompt.")
        
    return PromptTemplate(template=template_str, input_variables=["text"])

async def summarize_document_content(
    doc: Document, # This is the LangchainDocument from scraper.py
    llm_instance: GoogleGenerativeAI,
    custom_prompt_str: Optional[str] = None
) -> str:
    """
    Summarizes the content of a Document using the provided LLM instance.
    If plain text content (doc.page_content) is too short, 
    it attempts to use HTML content from doc.metadata.get('full_html_content').
    """
    if not llm_instance:
        logger.error("Summarization LLM not available.")
        return "Error: Summarization LLM not available."

    current_content_to_summarize = doc.page_content #
    content_source_description = "plain text"
    MIN_CONTENT_LENGTH = 50 # Define a constant for minimum length for summarization

    # Check if plain text is insufficient
    if not current_content_to_summarize or len(current_content_to_summarize.strip()) < MIN_CONTENT_LENGTH: #
        logger.info(
            f"Plain text content from '{doc.metadata.get('source', 'Unknown')}' is too short "
            f"(length: {len(current_content_to_summarize.strip() if current_content_to_summarize else 0)}). "
            f"Attempting to use HTML content."
        )
        html_content = doc.metadata.get('full_html_content') #
        
        if html_content and len(html_content.strip()) >= MIN_CONTENT_LENGTH:
            # Option 1: Use HTML directly (if LLM handles it well)
            current_content_to_summarize = html_content
            content_source_description = "HTML"
            logger.info(
                f"Using HTML content for '{doc.metadata.get('source', 'Unknown')}' for summarization. "
                f"HTML length: {len(current_content_to_summarize.strip())}."
            )

            # --- OPTIONAL: Convert HTML to text ---
            # If you find that your LLM doesn't handle raw HTML well for summarization,
            # you can uncomment the following block to convert HTML to plain text first.
            # You'll need to ensure BeautifulSoup is installed (`pip install beautifulsoup4`).
            # try:
            #     from bs4 import BeautifulSoup # Make sure to import at the top of the file
            #     soup = BeautifulSoup(html_content, 'html.parser')
            #     text_from_html = soup.get_text(separator=' ', strip=True)
            #     if len(text_from_html.strip()) >= MIN_CONTENT_LENGTH:
            #         current_content_to_summarize = text_from_html
            #         content_source_description = "text extracted from HTML"
            #         logger.info(
            #             f"Using text extracted from HTML for '{doc.metadata.get('source', 'Unknown')}' for summarization. "
            #             f"Extracted text length: {len(current_content_to_summarize.strip())}."
            #         )
            #     else:
            #         logger.warning(
            #             f"Text extracted from HTML for '{doc.metadata.get('source', 'Unknown')}' is also too short "
            #             f"(length: {len(text_from_html.strip())}). Will use raw HTML if it was selected, or fail if not."
            #         )
            #         # If HTML-extracted text is also too short, current_content_to_summarize might still be the raw HTML
            #         # or you might decide to revert to the original short plain text, or fail.
            #         # The current logic will proceed with raw HTML if text_from_html is too short.
            # except ImportError:
            #     logger.warning("BeautifulSoup not installed. Cannot convert HTML to text. Using raw HTML as fallback if selected.")
            # except Exception as e_html_parse:
            #     logger.error(f"Error parsing HTML for '{doc.metadata.get('source', 'Unknown')}': {e_html_parse}. Using raw HTML as fallback if selected.")
            # --- END OPTIONAL HTML TO TEXT ---
        else:
            logger.warning(
                f"HTML content for '{doc.metadata.get('source', 'Unknown')}' is also too short or unavailable. "
                f"Plain text length: {len(doc.page_content.strip() if doc.page_content else 0)}, "
                f"HTML length: {len(html_content.strip() if html_content else 0)}."
            )
            # current_content_to_summarize remains the original (short) page_content or None.
            # The final check below will catch this.
            
    # Final check on the chosen content before attempting summarization
    if not current_content_to_summarize or len(current_content_to_summarize.strip()) < MIN_CONTENT_LENGTH:
        logger.warning(
            f"Selected content ({content_source_description}) for '{doc.metadata.get('source', 'Unknown')}' "
            f"is still too short (length: {len(current_content_to_summarize.strip() if current_content_to_summarize else 0)}) or empty to summarize."
        )
        return "Content too short or empty to summarize."

    try:
        prompt_template = get_summarization_prompt_template(custom_prompt_str)
        
        # The chain expects a list of Document objects.
        # Create a new Document with the selected content for summarization, preserving metadata.
        document_for_chain = Document(page_content=current_content_to_summarize, metadata=doc.metadata)
        
        chain = load_summarize_chain(llm_instance, chain_type="stuff", prompt=prompt_template) #
        
        logger.info(
            f"Attempting to summarize URL: {document_for_chain.metadata.get('source', 'Unknown URL')} "
            f"(using {content_source_description}, length: {len(current_content_to_summarize.strip())}) "
            f"with prompt: \"{prompt_template.template[:100]}...\""
        )
        
        result = await chain.ainvoke({"input_documents": [document_for_chain]}) #
        summary = result.get("output_text", "").strip()

        if not summary:
            logger.warning(
                f"Empty summary received from LLM for URL: {document_for_chain.metadata.get('source', 'Unknown URL')} "
                f"(summarized from {content_source_description})."
            )
            return "Error: Summary generation resulted in empty output." #
        
        logger.info(
            f"Successfully summarized URL: {document_for_chain.metadata.get('source', 'Unknown URL')} "
            f"(from {content_source_description}). Summary length: {len(summary)}"
        )
        return summary
    except Exception as e:
        logger.error(
            f"ERROR during summarization for doc '{doc.metadata.get('source', 'Unknown URL')}' "
            f"(using {content_source_description}): {e}", exc_info=True
        )
        return f"Error generating summary: {str(e)}" #

# --- Tag Generation Specifics --- (assuming this and get_chat_response remain the same)
# ... (rest of your summarizer.py file)
def get_tag_generation_prompt_template(custom_prompt_str: Optional[str] = None) -> PromptTemplate: #
    """
    Returns the PromptTemplate for tag generation.
    Uses custom_prompt_str if provided and valid, otherwise defaults to config.DEFAULT_TAG_GENERATION_PROMPT.
    """
    template_str = custom_prompt_str if custom_prompt_str and "{text}" in custom_prompt_str else config.DEFAULT_TAG_GENERATION_PROMPT #
    if custom_prompt_str and "{text}" not in custom_prompt_str: #
        logger.warning(f"Custom tag generation prompt was provided but is missing '{{text}}' placeholder. Using default prompt.")
    return PromptTemplate(template=template_str, input_variables=["text"]) #

async def generate_tags_for_text( #
    text_content: str,
    llm_instance: GoogleGenerativeAI,
    custom_prompt_str: Optional[str] = None
) -> List[str]:
    """
    Generates a list of tags for the given text_content using the provided LLM instance.
    """
    if not llm_instance: #
        logger.error("Error: Tag generation LLM not available.")
        return []
    if not text_content or len(text_content.strip()) < 20: #
        logger.info(f"Content too short for tag generation. Length: {len(text_content.strip())}")
        return []

    try:
        prompt_template = get_tag_generation_prompt_template(custom_prompt_str) #
        formatted_prompt = await prompt_template.aformat(text=text_content) #
        
        logger.info(f"Attempting to generate tags with prompt (first 150 chars): \"{formatted_prompt[:150]}...\"")
        
        response_obj = await llm_instance.ainvoke(formatted_prompt) #
        tags_string = response_obj if isinstance(response_obj, str) else getattr(response_obj, 'text', str(response_obj)) #

        if not tags_string.strip(): #
            logger.warning("Empty tag string received from LLM.")
            return []

        tags_list = [tag.strip() for tag in tags_string.split(',') if tag.strip()] #
        
        logger.info(f"Successfully generated tags: {tags_list}. Raw string: '{tags_string}'")
        return tags_list #
    except Exception as e: #
        logger.error(f"ERROR during tag generation: {e}", exc_info=True)
        return []


# --- Chat Specifics ---
async def get_chat_response( #
    llm_instance: GoogleGenerativeAI,
    article_text: str,
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    custom_chat_prompt_str: Optional[str] = None
) -> str:
    """
    Generates a chat response based on article text, a question, and optional chat history.
    """
    if not llm_instance: #
        return "Error: Chat LLM not available."

    history_str_parts = []
    if chat_history: #
        for entry in chat_history:
            role = entry.get("role", "unknown").capitalize() #
            content = entry.get("content", "") #
            history_str_parts.append(f"{role}: {content}")
    full_history_str = "\n".join(history_str_parts) #

    base_prompt_template_str: str
    input_variables_for_template = ["question"] #

    if not article_text or len(article_text.strip()) < 20: #
        base_prompt_template_str = custom_chat_prompt_str if custom_chat_prompt_str and "{question}" in custom_chat_prompt_str else config.CHAT_NO_ARTICLE_PROMPT #
        if "{question}" not in base_prompt_template_str: # Fallback if even CHAT_NO_ARTICLE_PROMPT is misconfigured #
            base_prompt_template_str = "I'm sorry, but the article content could not be loaded, so I cannot answer your question about it."
            input_variables_for_template = [] # No variables needed for this specific fallback #
    else: # Article text is present #
        if custom_chat_prompt_str: #
            base_prompt_template_str = custom_chat_prompt_str
            # Determine necessary input variables based on placeholders in the custom prompt
            if "{article_text}" in base_prompt_template_str and "{question}" in base_prompt_template_str: #
                input_variables_for_template = ["article_text", "question"]
            elif "{question}" in base_prompt_template_str: # Allows prompts that might only use the question #
                input_variables_for_template = ["question"]
            else: # Fallback if custom prompt is missing essential placeholders #
                logger.warning("Custom chat prompt is missing required placeholders ({article_text} and/or {question}). Using default.")
                base_prompt_template_str = config.DEFAULT_CHAT_PROMPT #
                input_variables_for_template = ["article_text", "question"]
        else: # Default case when article_text is present #
            base_prompt_template_str = config.DEFAULT_CHAT_PROMPT #
            input_variables_for_template = ["article_text", "question"]

    final_prompt_parts = []
    try:
        current_prompt_text = base_prompt_template_str

        if not input_variables_for_template: # Handles the "no-article, no-question" specific fallback #
            final_prompt_parts.append(current_prompt_text)
        else: # Process prompts that expect variables #
            if "{article_text}" in current_prompt_text and "article_text" in input_variables_for_template: #
                current_prompt_text = current_prompt_text.replace("{article_text}", article_text)
            
            question_placeholder = "{question}"
            if question_placeholder in current_prompt_text: #
                parts = current_prompt_text.split(question_placeholder, 1) #
                final_prompt_parts.append(parts[0]) # Part before {question} #
                
                if full_history_str: #
                    final_prompt_parts.append(full_history_str)
                    final_prompt_parts.append("\n") 
                
                final_prompt_parts.append(f"User: {question}") # Current question #
                
                if len(parts) > 1: # If there was text after {question} (e.g., "\nAnswer:") #
                    final_prompt_parts.append(parts[1])
                else: # If prompt ended with {question}, add AI turn indicator #
                    final_prompt_parts.append("\nAI:")
            else:
                # This case implies input_variables were expected (e.g. custom prompt)
                # but the {question} placeholder itself was missing.
                logger.warning("Chat prompt expected {question} placeholder but it was missing. Appending history and question to the formatted prompt.")
                final_prompt_parts.append(current_prompt_text) # Append the (partially) formatted prompt
                if full_history_str: #
                    final_prompt_parts.append("\n" + full_history_str)
                final_prompt_parts.append(f"\nUser: {question}\nAI:")

    except Exception as e: #
        logger.error(f"Error formatting chat prompt: {e}. Using basic fallback prompt with history.", exc_info=True)
        final_prompt_parts.append(f"Article: {article_text}\n") # Basic fallback
        if full_history_str: #
            final_prompt_parts.append(full_history_str + "\n")
        final_prompt_parts.append(f"User: {question}\nAI:")

    final_formatted_prompt = "".join(final_prompt_parts) #

    logger.info(f"Attempting chat with final prompt (length: {len(final_formatted_prompt)}). First 200 chars: \"{final_formatted_prompt[:200]}...\"")
    try:
        response_obj = await llm_instance.ainvoke(final_formatted_prompt) #
        answer = response_obj if isinstance(response_obj, str) else getattr(response_obj, 'text', str(response_obj)) #
        
        logger.info(f"Chat LLM returned answer (length: {len(answer)}). First 100 chars: '{answer[:100]}...'")
        if not answer.strip(): #
            logger.warning("Empty answer received from chat LLM.")
            return "AI returned an empty answer."
        return answer.strip() #
    except Exception as e: #
        logger.error(f"ERROR getting answer from AI for chat: {e}", exc_info=True)
        return f"Error getting answer from AI: {str(e)}" #
