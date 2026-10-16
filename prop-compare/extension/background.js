// Clicking the toolbar icon opens the dashboard. All polling happens in the dashboard tab
// itself, so closing that tab stops every request to the books.
chrome.action.onClicked.addListener(() => chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') }));
