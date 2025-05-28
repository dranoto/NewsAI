// frontend/js/feedHandler.js
import * as state from './state.js';
import * as apiService from './apiService.js';
// uiManager will be needed to refresh filter buttons on the main page after feed changes.
// We'll need to pass the uiManager's renderFeedFilterButtons function or the whole module.
// For now, let's assume the main script will handle calling the uiManager update.

/**
 * This module handles all operations related to managing RSS feed sources
 * in the "Setup" tab, including adding, editing, deleting, and displaying feeds.
 */

// --- DOM Element References for Feed Management in Setup Tab ---
let addRssFeedForm, rssFeedUrlInput, rssFeedNameInput, rssFeedIntervalInput, rssFeedsListUI;

// Callback to refresh main page feed filter buttons, will be set by main script
let refreshMainFeedFilterButtonsCallback; 

/**
 * Initializes DOM references for the feed management UI elements.
 * Should be called once the DOM is ready.
 * @param {function} refreshFiltersCb - Callback to refresh main feed filter buttons.
 */
export function initializeFeedHandlerDOMReferences(refreshFiltersCb) {
    addRssFeedForm = document.getElementById('add-rss-feed-form');
    rssFeedUrlInput = document.getElementById('rss-feed-url-input');
    rssFeedNameInput = document.getElementById('rss-feed-name-input');
    rssFeedIntervalInput = document.getElementById('rss-feed-interval-input'); // For individual feed interval
    rssFeedsListUI = document.getElementById('rss-feeds-list');

    if (typeof refreshFiltersCb === 'function') {
        refreshMainFeedFilterButtonsCallback = refreshFiltersCb;
    } else {
        console.warn("FeedHandler: refreshMainFeedFilterButtonsCallback not provided during initialization. Filter buttons on main page may not update automatically after feed changes.");
    }

    console.log("FeedHandler: DOM references initialized.");
    if (!addRssFeedForm) console.error("FeedHandler: add-rss-feed-form not found!");
    if (!rssFeedsListUI) console.error("FeedHandler: rss-feeds-list not found!");
}

/**
 * Renders the list of RSS feeds in the Setup tab.
 * This list includes controls for editing and removing each feed.
 */
function renderRssFeedsListSetupUI() {
    if (!rssFeedsListUI) {
        console.error("FeedHandler: rssFeedsListUI element not found. Cannot render feeds list.");
        return;
    }
    rssFeedsListUI.innerHTML = ''; // Clear existing list

    if (state.dbFeedSources.length === 0) {
        rssFeedsListUI.innerHTML = '<li>No RSS feeds configured in the database. Add one below!</li>';
        return;
    }

    state.dbFeedSources.forEach((feed) => {
        const li = document.createElement('li');
        li.classList.add('feed-list-item'); // Add a class for styling

        let displayName = feed.name || (feed.url ? feed.url.split('/')[2]?.replace(/^www\./, '') : 'Unknown Feed');
        // Avoid overly long display names in this list too
        if (displayName.length > 50) displayName = displayName.substring(0, 47) + "...";


        const detailsSpan = document.createElement('span');
        detailsSpan.classList.add('feed-details');
        detailsSpan.innerHTML = `
            <strong>${displayName}</strong><br>
            <small class="feed-url-display">URL: ${feed.url}</small><br>
            <small>Interval: ${feed.fetch_interval_minutes}m</small>
        `;
        li.appendChild(detailsSpan);

        const controlsDiv = document.createElement('div');
        controlsDiv.classList.add('feed-controls');

        const editBtn = document.createElement('button');
        editBtn.textContent = 'Edit';
        editBtn.classList.add('edit-feed-btn', 'button-small'); // Add classes for styling
        editBtn.onclick = () => promptEditFeed(feed);
        controlsDiv.appendChild(editBtn);

        const removeBtn = document.createElement('button');
        removeBtn.textContent = 'Remove';
        removeBtn.classList.add('remove-feed-btn', 'button-small', 'button-danger'); // Add classes
        removeBtn.onclick = () => handleDeleteFeed(feed.id);
        controlsDiv.appendChild(removeBtn);

        li.appendChild(controlsDiv);
        rssFeedsListUI.appendChild(li);
    });
    console.log("FeedHandler: RSS feeds list in Setup tab rendered.");
}

/**
 * Fetches all feed sources from the backend, updates the shared state,
 * and then re-renders the feed list in the Setup tab and triggers
 * a refresh of the feed filter buttons on the main page.
 */
export async function loadAndRenderDbFeeds() {
    console.log("FeedHandler: Loading and rendering DB feeds...");
    try {
        const feeds = await apiService.fetchDbFeeds();
        state.setDbFeedSources(feeds || []); // Update shared state
        renderRssFeedsListSetupUI(); // Render list in Setup tab

        if (refreshMainFeedFilterButtonsCallback) {
            refreshMainFeedFilterButtonsCallback(); // Refresh filter buttons on main page
        }
    } catch (error) {
        console.error("FeedHandler: Error fetching DB feed sources:", error);
        state.setDbFeedSources([]); // Clear state on error
        renderRssFeedsListSetupUI(); // Render empty/error state
        if (rssFeedsListUI) { // Check if element exists before modifying
            const errorLi = document.createElement('li');
            errorLi.textContent = `Error loading feeds: ${error.message}`;
            errorLi.style.color = 'red';
            rssFeedsListUI.appendChild(errorLi);
        }
    }
}

/**
 * Handles the submission of the "Add RSS Feed" form.
 * @param {Event} event - The form submission event.
 */
async function handleAddFeedFormSubmit(event) {
    event.preventDefault();
    if (!rssFeedUrlInput || !rssFeedNameInput || !rssFeedIntervalInput) {
        console.error("FeedHandler: Add feed form elements not found.");
        return;
    }

    const url = rssFeedUrlInput.value.trim();
    const name = rssFeedNameInput.value.trim(); // Optional
    const intervalStr = rssFeedIntervalInput.value.trim(); // Optional
    let fetch_interval_minutes = state.globalRssFetchInterval; // Use global default from state

    if (!url) {
        alert("Feed URL is required.");
        return;
    }
    try {
        new URL(url); // Basic URL validation
    } catch (_) {
        alert("Invalid Feed URL format.");
        return;
    }

    if (intervalStr) {
        const parsedInterval = parseInt(intervalStr);
        if (isNaN(parsedInterval) || parsedInterval < 5) { // Assuming min 5 minutes
            alert("Invalid fetch interval. Please enter a positive number (minimum 5 minutes) or leave blank for default.");
            return;
        }
        fetch_interval_minutes = parsedInterval;
    }

    const feedData = {
        url: url,
        name: name || null, // Send null if empty, backend can derive name
        fetch_interval_minutes: fetch_interval_minutes
    };

    try {
        const newFeed = await apiService.addRssFeed(feedData);
        alert(`Feed "${newFeed.name || newFeed.url}" added successfully!`);
        // Clear form fields
        rssFeedUrlInput.value = '';
        rssFeedNameInput.value = '';
        rssFeedIntervalInput.value = '';
        // Refresh the list of feeds
        await loadAndRenderDbFeeds();
    } catch (error) {
        console.error("FeedHandler: Error adding feed:", error);
        alert(`Error adding feed: ${error.message}`);
    }
}

/**
 * Prompts the user to edit a feed's name and interval.
 * @param {object} feed - The feed object to edit.
 */
async function promptEditFeed(feed) {
    const newName = prompt("Enter new name for the feed (or leave blank to keep current):", feed.name || "");
    const newIntervalStr = prompt(`Enter new fetch interval in minutes for "${feed.name || feed.url}" (leave blank to keep ${feed.fetch_interval_minutes}m, min 5):`, feed.fetch_interval_minutes);

    const updatePayload = {};
    let changed = false;

    // Check name change
    if (newName !== null) { // User didn't cancel prompt
        if (newName.trim() !== (feed.name || "")) { // Actual change in value
            updatePayload.name = newName.trim() === "" ? null : newName.trim(); // Allow setting to null (empty)
            changed = true;
        } else if (newName.trim() === "" && feed.name) { // Explicitly clearing a name
             updatePayload.name = null;
             changed = true;
        }
    }
    
    // Check interval change
    if (newIntervalStr !== null) { // User didn't cancel prompt
        if (newIntervalStr.trim() === "") {
            // No change if blank, unless explicitly clearing to use default (not supported by current backend PUT)
        } else {
            const newInterval = parseInt(newIntervalStr);
            if (!isNaN(newInterval) && newInterval >= 5 && newInterval !== feed.fetch_interval_minutes) {
                updatePayload.fetch_interval_minutes = newInterval;
                changed = true;
            } else if (newIntervalStr.trim() !== "" && (isNaN(newInterval) || newInterval < 5)) {
                alert("Invalid interval. Please enter a positive number (minimum 5 minutes).");
                return; // Don't proceed if interval is invalid
            }
        }
    }


    if (changed) {
        try {
            await apiService.updateRssFeed(feed.id, updatePayload);
            alert("Feed updated successfully!");
            await loadAndRenderDbFeeds(); // Refresh list
        } catch (error) {
            console.error("FeedHandler: Error updating feed:", error);
            alert(`Error updating feed: ${error.message}`);
        }
    } else {
        alert("No changes made to the feed.");
    }
}

/**
 * Handles the deletion of an RSS feed.
 * @param {number} feedId - The ID of the feed to delete.
 */
async function handleDeleteFeed(feedId) {
    // Find feed name for confirmation message
    const feedToDelete = state.dbFeedSources.find(f => f.id === feedId);
    const feedNameToConfirm = feedToDelete ? (feedToDelete.name || feedToDelete.url) : `ID ${feedId}`;

    if (!confirm(`Are you sure you want to remove feed "${feedNameToConfirm}" and all its articles/summaries? This cannot be undone.`)) {
        return;
    }
    try {
        await apiService.deleteRssFeed(feedId);
        alert("Feed deleted successfully!");
        // Update state by removing the feed
        state.setDbFeedSources(state.dbFeedSources.filter(f => f.id !== feedId));
        // Refresh the UI
        renderRssFeedsListSetupUI(); // Re-render setup list
        if (refreshMainFeedFilterButtonsCallback) {
            refreshMainFeedFilterButtonsCallback(); // Refresh filter buttons on main page
        }
        // Also, if the deleted feed was an active filter, clear it
        if (state.activeFeedFilterIds.includes(feedId)) {
            state.setActiveFeedFilterIds(state.activeFeedFilterIds.filter(id => id !== feedId));
            // Potentially trigger a refresh of the main article feed if needed
            // This would require a callback to the main script's fetchAndDisplaySummaries
        }

    } catch (error) {
        console.error("FeedHandler: Error deleting feed:", error);
        alert(`Error deleting feed: ${error.message}`);
    }
}

/**
 * Sets up event listeners for feed management actions (e.g., add feed form).
 * Dynamic listeners for edit/remove are attached when the list is rendered.
 */
export function setupFeedHandlerEventListeners() {
    if (addRssFeedForm) {
        addRssFeedForm.addEventListener('submit', handleAddFeedFormSubmit);
    } else {
        console.warn("FeedHandler: Add RSS Feed form not found. Cannot attach submit listener.");
    }
    console.log("FeedHandler: Event listeners (add form) set up.");
}

console.log("frontend/js/feedHandler.js: Module loaded.");
