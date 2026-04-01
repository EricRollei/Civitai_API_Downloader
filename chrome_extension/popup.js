// Popup script for Civitai to Desktop extension

const SERVER_URL = "http://127.0.0.1:7865";

let currentUrl = "";
let isConnected = false;

// Initialize popup
document.addEventListener("DOMContentLoaded", async () => {
  // Get current tab URL
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = tab?.url || "";
  
  // Update URL preview
  const urlText = document.getElementById("urlText");
  const urlPreview = document.getElementById("urlPreview");
  const content = document.getElementById("content");
  const notCivitai = document.getElementById("notCivitai");
  
  const isCivitaiUrl = currentUrl.includes("civitai.com");
  
  if (isCivitaiUrl) {
    urlText.textContent = currentUrl;
    urlPreview.classList.add("civitai");
    content.style.display = "block";
    notCivitai.style.display = "none";
  } else {
    content.style.display = "none";
    notCivitai.style.display = "block";
  }
  
  // Check server status
  await checkStatus();
  
  // Setup send button
  const sendBtn = document.getElementById("sendBtn");
  sendBtn.addEventListener("click", sendUrl);
});

async function checkStatus() {
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const sendBtn = document.getElementById("sendBtn");
  
  try {
    const response = await fetch(`${SERVER_URL}/status`);
    if (response.ok) {
      statusDot.classList.add("connected");
      statusText.textContent = "Desktop app connected";
      isConnected = true;
      
      // Enable button if we're on a Civitai page
      if (currentUrl.includes("civitai.com")) {
        sendBtn.disabled = false;
      }
    } else {
      throw new Error("Server not responding");
    }
  } catch (error) {
    statusDot.classList.remove("connected");
    statusText.textContent = "Desktop app not running";
    isConnected = false;
    sendBtn.disabled = true;
  }
}

async function sendUrl() {
  const sendBtn = document.getElementById("sendBtn");
  const message = document.getElementById("message");
  
  sendBtn.disabled = true;
  sendBtn.innerHTML = "<span>⏳</span> Sending...";
  
  try {
    const response = await fetch(`${SERVER_URL}/send-url`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url: currentUrl }),
    });
    
    if (response.ok) {
      message.textContent = "✓ URL sent to desktop app!";
      message.className = "message success";
      sendBtn.innerHTML = "<span>✓</span> Sent!";
      
      // Close popup after a short delay
      setTimeout(() => {
        window.close();
      }, 1000);
    } else {
      throw new Error("Failed to send");
    }
  } catch (error) {
    message.textContent = "✗ Failed to send URL. Is the app running?";
    message.className = "message error";
    sendBtn.innerHTML = "<span>📤</span> Send to Desktop App";
    sendBtn.disabled = false;
  }
}
