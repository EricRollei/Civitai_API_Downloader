// Background service worker for Civitai to Desktop extension

const SERVER_URL = "http://127.0.0.1:7865";

// Listen for keyboard shortcut
chrome.commands.onCommand.addListener(async (command) => {
  console.log("Command received:", command);
  if (command === "send-to-desktop") {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    console.log("Current tab:", tab?.url);
    if (tab && tab.url) {
      const result = await sendUrlToDesktop(tab.url);
      // Show a brief badge to indicate success/failure
      if (result.success) {
        chrome.action.setBadgeText({ text: "✓", tabId: tab.id });
        chrome.action.setBadgeBackgroundColor({ color: "#44aa44", tabId: tab.id });
      } else {
        chrome.action.setBadgeText({ text: "!", tabId: tab.id });
        chrome.action.setBadgeBackgroundColor({ color: "#aa4444", tabId: tab.id });
      }
      // Clear badge after 2 seconds
      setTimeout(() => {
        chrome.action.setBadgeText({ text: "", tabId: tab.id });
      }, 2000);
    }
  }
});

// Function to send URL to desktop app
async function sendUrlToDesktop(url) {
  // Only send Civitai URLs
  if (!url.includes("civitai.com")) {
    console.log("Not a Civitai URL, ignoring:", url);
    return { success: false, error: "Not a Civitai URL" };
  }

  try {
    const response = await fetch(`${SERVER_URL}/send-url`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url: url }),
    });

    if (response.ok) {
      const data = await response.json();
      console.log("URL sent successfully:", data);
      return { success: true, data };
    } else {
      console.error("Failed to send URL:", response.status);
      return { success: false, error: `Server returned ${response.status}` };
    }
  } catch (error) {
    console.error("Error sending URL:", error);
    return { success: false, error: error.message };
  }
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "sendUrl") {
    sendUrlToDesktop(request.url).then(sendResponse);
    return true; // Keep the message channel open for async response
  }
  if (request.action === "checkStatus") {
    checkServerStatus().then(sendResponse);
    return true;
  }
});

// Check if desktop app is running
async function checkServerStatus() {
  try {
    const response = await fetch(`${SERVER_URL}/status`, {
      method: "GET",
    });
    if (response.ok) {
      return { running: true };
    }
    return { running: false };
  } catch (error) {
    return { running: false, error: error.message };
  }
}
