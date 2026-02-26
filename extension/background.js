/**
 * Background listener that monitors tab updates.
 * This ensures the extension knows when the user navigates to a new YouTube video.
 */
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    // Detect if the page has finished loading and is a valid YouTube video watch page
    if (changeInfo.status === 'complete' && tab.url && tab.url.includes("youtube.com/watch")) {
        
        // Update local storage to track the current URL and set a flag ('needsResync').
        // This allows the Popup or Content Script to trigger a new transcript fetch automatically.
        chrome.storage.local.set({ 
            lastVideoUrl: tab.url, 
            needsResync: true 
        });
    }
});