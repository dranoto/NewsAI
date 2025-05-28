// frontend/js/chatHandler.js
import * as state from './state.js';
import * as apiService from './apiService.js';
// Assuming 'marked' library is available globally for Markdown parsing.
// If not, it would need to be imported or handled differently.

/**
 * This module handles all functionalities related to the article chat modal.
 */

// --- DOM Element References for Chat Modal ---
let articleChatModal, closeArticleChatModalBtn,
    chatModalArticlePreviewContent, chatModalHistory,
    chatModalQuestionInput, chatModalAskButton;

/**
 * Initializes DOM references for the chat modal elements.
 * Should be called once the DOM is ready.
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
 * @param {HTMLElement} responseDiv - The DOM element where history should be rendered.
 * @param {Array<object>} historyArray - The array of chat history items ({role, content}).
 */
function renderChatHistoryInModal(responseDiv, historyArray) {
    if (!responseDiv) {
        console.error("ChatHandler: renderChatHistoryInModal - responseDiv is null.");
        return;
    }
    responseDiv.innerHTML = ''; // Clear previous content

    if (!historyArray || historyArray.length === 0) {
        // No history to display, or an empty placeholder can be added if desired.
        // responseDiv.innerHTML = '<p class="chat-placeholder">No chat history yet. Ask a question!</p>';
        return;
    }

    historyArray.forEach(chatItem => {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add(chatItem.role === 'user' ? 'chat-history-q' : 'chat-history-a');
        
        // Use marked.parse if available, otherwise just textContent
        const content = chatItem.content || (chatItem.role === 'ai' ? "Processing..." : "");
        try {
            if (typeof marked !== 'undefined') {
                messageDiv.innerHTML = `<strong>${chatItem.role === 'user' ? 'You' : 'AI'}:</strong> ${marked.parse(content)}`;
            } else {
                messageDiv.innerHTML = `<strong>${chatItem.role === 'user' ? 'You' : 'AI'}:</strong> ${content.replace(/\n/g, '<br>')}`; // Basic newline handling
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

    // Auto-scroll to the bottom
    if (responseDiv.scrollHeight > responseDiv.clientHeight) {
        responseDiv.scrollTop = responseDiv.scrollHeight;
    }
}

/**
 * Fetches and displays the chat history for a given article in the modal.
 * This function includes the fix for correctly processing fetched history.
 * @param {number} articleId - The ID of the article.
 */
async function fetchAndDisplayChatHistoryForModal(articleId) {
    if (!chatModalHistory) {
        console.error("ChatHandler: chatModalHistory element not found for fetching history.");
        return;
    }
    chatModalHistory.innerHTML = '<p class="chat-loading">Loading chat history...</p>';
    state.setCurrentChatHistory([]); // Reset local state history cache

    try {
        const historyFromServer = await apiService.fetchChatHistory(articleId); // API call
        
        // ** THE FIX IS HERE **
        // The historyFromServer is already an array of {role, content} objects.
        // We directly use this to set our state and render.
        state.setCurrentChatHistory(historyFromServer || []); 

        renderChatHistoryInModal(chatModalHistory, state.currentChatHistory);
    } catch (error) {
        console.error('ChatHandler: Error fetching or displaying chat history:', error);
        if (chatModalHistory) { // Check again in case it became null
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
    state.setCurrentChatHistory([]); // Reset/clear history for the new session in the state

    // Populate article preview in the modal
    chatModalArticlePreviewContent.innerHTML = `
        <h4>${articleData.title || 'No Title'}</h4>
        <div class="article-summary-preview">
            ${typeof marked !== 'undefined' ? marked.parse(articleData.summary || 'No summary available.') : (articleData.summary || 'No summary available.')}
        </div>
        <a href="${articleData.url}" target="_blank" rel="noopener noreferrer" class="article-link-modal">Read Full Article</a>
    `;

    chatModalHistory.innerHTML = ''; // Clear previous visual history
    fetchAndDisplayChatHistoryForModal(articleData.id); // Fetch and display history

    articleChatModal.style.display = "block";
    chatModalQuestionInput.value = ''; // Clear question input
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
    state.setCurrentChatHistory([]); // Clear history state on close
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

    // Add user's question to currentChatHistory state and re-render immediately
    const userMessage = { role: 'user', content: question };
    state.currentChatHistory.push(userMessage); // Update state directly
    renderChatHistoryInModal(chatModalHistory, state.currentChatHistory);

    // Show temporary loading/thinking indicator for AI response
    const thinkingMessage = { role: 'ai', content: 'AI is thinking...'};
    state.currentChatHistory.push(thinkingMessage);
    renderChatHistoryInModal(chatModalHistory, state.currentChatHistory); // Re-render with thinking message


    chatModalQuestionInput.value = ''; // Clear input field
    chatModalQuestionInput.disabled = true;
    chatModalAskButton.disabled = true;

    try {
        const payload = {
            article_id: articleDbId,
            question: question,
            // Use currentChatPrompt from state, fallback to default if not set (though state should handle this)
            chat_prompt: (state.currentChatPrompt !== state.defaultChatPrompt) ? state.currentChatPrompt : null,
            // Send chat history *before* the current user question and AI thinking message
            chat_history: state.currentChatHistory.slice(0, -2) 
        };
        
        const data = await apiService.postChatMessage(payload); // API call
        const answer = data.answer || "No answer received.";

        // Remove the "AI is thinking..." message
        state.currentChatHistory.pop(); 
        // Add AI's actual answer to state and re-render
        state.currentChatHistory.push({ role: 'ai', content: answer });
        renderChatHistoryInModal(chatModalHistory, state.currentChatHistory);

        if (data.error_message) {
            console.warn("ChatHandler: Error message from backend chat response:", data.error_message);
            // Optionally display this error in the chat UI as an AI message if not already part of 'answer'
        }

    } catch (error) {
        console.error('ChatHandler: Error during modal article chat submission:', error);
        // Remove "AI is thinking..."
        state.currentChatHistory.pop();
        // Add error to local history and render
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

    // Close modal if clicked outside of its content area
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
            if (event.key === 'Enter' && !event.shiftKey) { // Allow shift+enter for newlines if desired
                event.preventDefault(); // Prevent default form submission/newline
                handleModalArticleChatSubmit();
            }
        });
    }
    console.log("ChatHandler: Chat modal event listeners set up.");
}

console.log("frontend/js/chatHandler.js: Module loaded.");
