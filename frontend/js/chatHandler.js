// frontend/js/chatHandler.js
import * as state from './state.js';
import * as apiService from './apiService.js';
// Assuming 'marked' library is available globally for Markdown parsing.

/**
 * This module handles all functionalities related to the article chat modal.
 */

// --- DOM Element References for Chat Modal ---
let articleChatModal, closeArticleChatModalBtn,
    chatModalArticlePreviewContent, chatModalHistory,
    chatModalQuestionInput, chatModalAskButton;

/**
 * Initializes DOM references for the chat modal elements.
 */
export function initializeChatDOMReferences() {
    articleChatModal = document.getElementById('article-chat-modal');
    closeArticleChatModalBtn = document.getElementById('close-article-chat-modal-btn');
    chatModalArticlePreviewContent = document.getElementById('chat-modal-article-preview-content');
    chatModalHistory = document.getElementById('chat-modal-history');
    chatModalQuestionInput = document.getElementById('chat-modal-question-input');
    chatModalAskButton = document.getElementById('chat-modal-ask-button');
    console.log("ChatHandler: DOM references for chat modal initialized.");
}

/**
 * Renders the chat history in the modal's display area.
 */
function renderChatHistoryInModal(responseDiv, historyArray) {
    if (!responseDiv) {
        console.error("ChatHandler: renderChatHistoryInModal - responseDiv is null.");
        return;
    }
    responseDiv.innerHTML = ''; 

    if (!historyArray || historyArray.length === 0) {
        return;
    }

    historyArray.forEach(chatItem => {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add(chatItem.role === 'user' ? 'chat-history-q' : 'chat-history-a');
        
        const content = chatItem.content || (chatItem.role === 'ai' ? "Processing..." : "");
        try {
            if (typeof marked !== 'undefined') {
                messageDiv.innerHTML = `<strong>${chatItem.role === 'user' ? 'You' : 'AI'}:</strong> ${marked.parse(content)}`;
            } else {
                messageDiv.innerHTML = `<strong>${chatItem.role === 'user' ? 'You' : 'AI'}:</strong> ${content.replace(/\n/g, '<br>')}`;
            }
        } catch (e) {
            console.error("ChatHandler: Error parsing markdown for chat message", e);
            messageDiv.textContent = `${chatItem.role === 'user' ? 'You' : 'AI'}: ${content}`;
        }
        
        if (chatItem.role === 'ai' && content && (content.startsWith("AI Error:") || content.startsWith("Error:"))) {
            messageDiv.classList.add('error-message');
        }
        responseDiv.appendChild(messageDiv);
    });

    if (responseDiv.scrollHeight > responseDiv.clientHeight) {
        responseDiv.scrollTop = responseDiv.scrollHeight;
    }
}

/**
 * Fetches and displays the chat history for a given article in the modal.
 */
async function fetchAndDisplayChatHistoryForModal(articleId) {
    if (!chatModalHistory) {
        console.error("ChatHandler: chatModalHistory element not found for fetching history.");
        return;
    }
    chatModalHistory.innerHTML = '<p class="chat-loading">Loading chat history...</p>';
    state.setCurrentChatHistory([]); 

    try {
        const historyFromServer = await apiService.fetchChatHistory(articleId); 
        state.setCurrentChatHistory(historyFromServer || []); 
        renderChatHistoryInModal(chatModalHistory, state.currentChatHistory);
    } catch (error) {
        console.error('ChatHandler: Error fetching or displaying chat history:', error);
        if (chatModalHistory) { 
            chatModalHistory.innerHTML = `<p class="error-message">Error loading chat history: ${error.message}</p>`;
        }
    }
}

/**
 * Opens the article chat modal and populates it with article data and chat history.
 * @param {object} articleData - The data for the article to chat about.
 */
export function openArticleChatModal(articleData) {
    if (!articleChatModal || !chatModalArticlePreviewContent || !chatModalHistory || !chatModalQuestionInput) {
        console.error("ChatHandler: One or more chat modal DOM elements are missing. Cannot open modal.");
        return;
    }
    state.setCurrentArticleForChat(articleData);
    state.setCurrentChatHistory([]); 

    // Populate article preview in the modal
    // REMOVED the "Read Full Article" link from this preview
    chatModalArticlePreviewContent.innerHTML = `
        <h4>${articleData.title || 'No Title'}</h4>
        <div class="article-summary-preview">
            ${typeof marked !== 'undefined' ? marked.parse(articleData.summary || 'No summary available.') : (articleData.summary || 'No summary available.')}
        </div>
        <p class="chat-modal-source-info">
            Source: ${articleData.publisher || 'N/A'} | 
            Published: ${articleData.published_date ? new Date(articleData.published_date).toLocaleDateString() : 'N/A'}
        </p>
    `; // Added source/date info, removed full article link

    chatModalHistory.innerHTML = ''; 
    fetchAndDisplayChatHistoryForModal(articleData.id); 

    articleChatModal.style.display = "block";
    chatModalQuestionInput.value = ''; 
    chatModalQuestionInput.focus();
    console.log(`ChatHandler: Opened chat modal for article ID: ${articleData.id}`);
}

/**
 * Closes the article chat modal and clears related state.
 */
export function closeArticleChatModal() {
    if (articleChatModal) {
        articleChatModal.style.display = "none";
    }
    state.setCurrentArticleForChat(null);
    state.setCurrentChatHistory([]); 
    console.log("ChatHandler: Chat modal closed.");
}

/**
 * Handles the submission of a new chat question from the modal.
 */
async function handleModalArticleChatSubmit() {
    if (!state.currentArticleForChat || !chatModalQuestionInput || !chatModalHistory || !chatModalAskButton) {
        console.error("ChatHandler: Missing current article or modal elements for chat submission.");
        return;
    }

    const articleDbId = state.currentArticleForChat.id;
    const question = chatModalQuestionInput.value.trim();
    if (!question) {
        alert('Please enter a question.');
        return;
    }

    const userMessage = { role: 'user', content: question };
    state.currentChatHistory.push(userMessage); 
    renderChatHistoryInModal(chatModalHistory, state.currentChatHistory);

    const thinkingMessage = { role: 'ai', content: 'AI is thinking...'};
    state.currentChatHistory.push(thinkingMessage);
    renderChatHistoryInModal(chatModalHistory, state.currentChatHistory); 


    chatModalQuestionInput.value = ''; 
    chatModalQuestionInput.disabled = true;
    chatModalAskButton.disabled = true;

    try {
        const payload = {
            article_id: articleDbId,
            question: question,
            chat_prompt: (state.currentChatPrompt !== state.defaultChatPrompt) ? state.currentChatPrompt : null,
            chat_history: state.currentChatHistory.slice(0, -2) 
        };
        
        const data = await apiService.postChatMessage(payload); 
        const answer = data.answer || "No answer received.";

        state.currentChatHistory.pop(); 
        state.currentChatHistory.push({ role: 'ai', content: answer });
        renderChatHistoryInModal(chatModalHistory, state.currentChatHistory);

        if (data.error_message) {
            console.warn("ChatHandler: Error message from backend chat response:", data.error_message);
        }

    } catch (error) {
        console.error('ChatHandler: Error during modal article chat submission:', error);
        state.currentChatHistory.pop();
        state.currentChatHistory.push({ role: 'ai', content: `AI Error: ${error.message}` });
        renderChatHistoryInModal(chatModalHistory, state.currentChatHistory);
    } finally {
        chatModalQuestionInput.disabled = false;
        chatModalAskButton.disabled = false;
        if (chatModalHistory && chatModalHistory.scrollHeight > chatModalHistory.clientHeight) {
            chatModalHistory.scrollTop = chatModalHistory.scrollHeight;
        }
        chatModalQuestionInput.focus();
    }
}

/**
 * Sets up event listeners for the chat modal.
 */
export function setupChatModalEventListeners() {
    if (!articleChatModal) {
        console.warn("ChatHandler: Chat modal element not found. Cannot set up event listeners.");
        return;
    }

    if (closeArticleChatModalBtn) {
        closeArticleChatModalBtn.onclick = closeArticleChatModal;
    }

    window.addEventListener('click', function(event) {
        if (event.target === articleChatModal) {
            closeArticleChatModal();
        }
    });

    if (chatModalAskButton) {
        chatModalAskButton.onclick = handleModalArticleChatSubmit;
    }

    if (chatModalQuestionInput) {
        chatModalQuestionInput.addEventListener('keypress', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) { 
                event.preventDefault(); 
                handleModalArticleChatSubmit();
            }
        });
    }
    console.log("ChatHandler: Chat modal event listeners set up.");
}

console.log("frontend/js/chatHandler.js: Module loaded.");
