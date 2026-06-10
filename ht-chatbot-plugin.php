<?php
/**
 * Plugin Name: HT LMS Chatbot
 * Description: Floating AI chatbot widget connected to FastAPI backend, with lesson ingestion.
 * Version: 1.3
 */

// ─────────────────────────────────────────────────────────────────────────────
// 1. DATA SENDER: Sends lesson data to FastAPI when an instructor updates a lesson
// ─────────────────────────────────────────────────────────────────────────────
add_action('save_post', 'ht_sync_lesson_to_fastapi', 10, 3);
function ht_sync_lesson_to_fastapi($post_id, $post, $update) {
    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) return;
    if ($post->post_status !== 'publish') return;
    if ($post->post_type !== 'post') return; // Adjust to 'lesson' if using a Custom Post Type

    // ── Extract video context BEFORE stripping tags ──────────────────────────
    $video_context = '';

    // Detect YouTube embeds (iframe or shortcode URLs)
    preg_match_all(
        '/(?:youtube\.com\/embed\/|youtu\.be\/|youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})/',
        $post->post_content,
        $yt_matches
    );
    if (!empty($yt_matches[1])) {
        $video_ids = array_unique($yt_matches[1]);
        $video_context .= "\n[Note: This lesson contains " . count($video_ids) . " embedded YouTube video(s). Video ID(s): " . implode(', ', $video_ids) . ". You cannot watch these, but acknowledge they exist if asked.]";
    }

    // Detect HTML5 <video> tags
    preg_match_all('/<video[^>]+src=["\']([^"\']+)["\']/i', $post->post_content, $vid_matches);
    if (!empty($vid_matches[1])) {
        $video_context .= "\n[Note: This lesson contains an embedded HTML5 video file(s): " . implode(', ', $vid_matches[1]) . "]";
    }

    // Detect [video] shortcodes
    if (has_shortcode($post->post_content, 'video')) {
        preg_match_all('/\[video[^\]]*src=["\']([^"\']+)["\']/i', $post->post_content, $sc_matches);
        if (!empty($sc_matches[1])) {
            $video_context .= "\n[Note: This lesson contains a WordPress video shortcode. Source: " . implode(', ', $sc_matches[1]) . "]";
        }
    }
    // ─────────────────────────────────────────────────────────────────────────

    $clean_text = wp_strip_all_tags(strip_shortcodes($post->post_content)) . $video_context;

    // ── Extract images ────────────────────────────────────────────────────────
    $image_urls = array();
    preg_match_all('/<img[^>]+src=["\']([^"\']+)["\']/i', $post->post_content, $matches);
    if (!empty($matches[1])) {
        $image_urls = array_merge($image_urls, $matches[1]);
    }
    if (has_post_thumbnail($post_id)) {
        $featured = get_the_post_thumbnail_url($post_id, 'full');
        if ($featured) $image_urls[] = $featured;
    }
    $image_urls = array_values(array_unique($image_urls));

    // Send image URLs directly — the FastAPI backend fetches and analyzes them via vision model
    $payload = array(
        'lesson_id'     => 'lesson_' . $post_id,
        'instructor_id' => 'instructor_' . $post->post_author,
        'content'       => $clean_text,
        'image_urls'    => $image_urls
    );

    $api_url = 'https://lms-chatbot-api.vercel.app/api/ingest';
    $api_key = 'test_key_123';

    $response = wp_remote_post($api_url, array(
        'method'   => 'POST',
        'blocking' => true,
        'headers'  => array(
            'Content-Type' => 'application/json',
            'X-API-Key'    => $api_key
        ),
        'body'    => json_encode($payload),
        'timeout' => 45
    ));

    if (is_wp_error($response)) {
        error_log("Ingestion failed: " . $response->get_error_message());
    } else {
        error_log("Ingestion response code: " . wp_remote_retrieve_response_code($response));
        error_log("Ingestion response body: " . wp_remote_retrieve_body($response));
    }
}

// ht_convert_image_url_to_base64() removed — images are now sent as plain URLs


// ─────────────────────────────────────────────────────────────────────────────
// 2. UI INJECTOR: Injects the floating HTML Chat window into the footer
// ─────────────────────────────────────────────────────────────────────────────
add_action('wp_footer', 'ht_inject_chatbot_ui');
function ht_inject_chatbot_ui() {
    if (!is_single() && !is_category()) return;

    if (is_category()) {
        $category   = get_queried_object();
        $context_id = 'category_' . $category->slug;
    } else {
        global $post;
        $context_id = 'lesson_' . $post->ID;
    }
    ?>
    <script>window.WP_CHAT_CONTEXT = { lesson_id: "<?php echo esc_js($context_id); ?>" };</script>
    <div id="ht-chat-widget">
        <!-- Chat icon uses CSS background-image (immune to theme SVG resets) -->
        <button id="ht-chat-toggle" class="ht-chat-btn" aria-label="Open chat"></button>
        <div id="ht-chat-window" class="ht-chat-hidden">
            <div class="ht-chat-header">
                <h3>¡Vamos! Assistant</h3>
                <button id="ht-chat-close" aria-label="Close chat">×</button>
            </div>
            <div id="ht-chat-messages" class="ht-chat-body">
                <div class="ht-message system">Hello! I can answer questions strictly about this specific page content. Ask away!</div>
            </div>
            <div class="ht-chat-footer">
                <textarea id="ht-chat-input" placeholder="Ask me about this lesson..." autocomplete="off" rows="1"></textarea>
                <button id="ht-chat-send">Send</button>
            </div>
        </div>
    </div>
    <?php
}


// ─────────────────────────────────────────────────────────────────────────────
// 3. STYLE INJECTOR: Injects clean glassmorphism styling into the header
// ─────────────────────────────────────────────────────────────────────────────
add_action('wp_head', 'ht_inject_chatbot_styles');
function ht_inject_chatbot_styles() {
    if (!is_single() && !is_category()) return;
    ?>
    <style>
        /* ── Widget Container ─────────────────────────────────────────────── */
        #ht-chat-widget {
            position: fixed;
            bottom: 30px;
            right: 30px;
            z-index: 999999;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }

        /* ── Toggle Button — Red brand color, CSS background-image SVG (theme-proof) ── */
        .ht-chat-btn {
            width: 60px;
            height: 60px;
            background-color: #CC1111;
            /* Chat bubble SVG — white icon on red background */
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='28' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: center center;
            background-size: 28px 28px;
            border-radius: 50%;
            border: none;
            cursor: pointer;
            box-shadow: 0 4px 20px rgba(204, 17, 17, 0.4);
            transition: transform 0.2s, box-shadow 0.2s;
            padding: 0;
            outline: none;
            -webkit-appearance: none;
            appearance: none;
        }
        .ht-chat-btn:hover {
            transform: scale(1.08);
            background-color: #aa0e0e;
            box-shadow: 0 6px 24px rgba(204, 17, 17, 0.55);
        }

        /* ── Chat Window ──────────────────────────────────────────────────── */
        #ht-chat-window {
            width: 360px;
            height: 500px;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(204, 17, 17, 0.15);
            border-radius: 16px;
            position: absolute;
            bottom: 80px;
            right: 0;
            display: flex;
            flex-direction: column;
            box-shadow: 0 8px 40px rgba(204, 17, 17, 0.15), 0 2px 8px rgba(0,0,0,0.08);
            overflow: hidden;
        }
        .ht-chat-hidden { display: none !important; }

        /* ── Header — matches site's red brand ────────────────────────────── */
        .ht-chat-header {
            background: linear-gradient(135deg, #CC1111 0%, #a80d0d 100%);
            color: white;
            padding: 14px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 3px solid rgba(0,0,0,0.1);
        }
        .ht-chat-header h3 {
            margin: 0;
            font-size: 15px;
            font-weight: 700;
            color: white;
            letter-spacing: 0.3px;
        }
        #ht-chat-close {
            background: rgba(255,255,255,0.15);
            border: none;
            color: white;
            font-size: 20px;
            cursor: pointer;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            line-height: 1;
            transition: background 0.2s;
            padding: 0;
        }
        #ht-chat-close:hover { background: rgba(255,255,255,0.3); }

        /* ── Message Body ─────────────────────────────────────────────────── */
        .ht-chat-body {
            flex: 1;
            padding: 15px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 10px;
            font-size: 14px;
        }
        .ht-chat-body::-webkit-scrollbar { width: 6px; }
        .ht-chat-body::-webkit-scrollbar-track { background: transparent; }
        .ht-chat-body::-webkit-scrollbar-thumb { background: rgba(204, 17, 17, 0.2); border-radius: 10px; }
        .ht-chat-body::-webkit-scrollbar-thumb:hover { background: rgba(204, 17, 17, 0.4); }

        /* ── Message Bubbles ──────────────────────────────────────────────── */
        .ht-message {
            padding: 10px 14px;
            border-radius: 12px;
            max-width: 85%;
            line-height: 1.4;
            word-wrap: break-word;
        }
        .ht-message.system {
            background: #fff3f3;
            color: #7a0000;
            align-self: flex-start;
            border-bottom-left-radius: 2px;
            border: 1px solid rgba(204,17,17,0.1);
            font-style: italic;
            font-size: 13px;
        }
        .ht-message.user {
            background: linear-gradient(135deg, #CC1111, #a80d0d);
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 2px;
            box-shadow: 0 2px 8px rgba(204,17,17,0.25);
        }
        .ht-message.bot {
            background: #fff8f8;
            color: #2d0000;
            align-self: flex-start;
            border-bottom-left-radius: 2px;
            border: 1px solid rgba(204,17,17,0.1);
        }

        /* ── Markdown Styles for Bot Responses ───────────────────────────── */
        /* ── Markdown Styles for Bot Responses — red accent palette ─────── */
        .ht-message.bot h1,
        .ht-message.bot h2,
        .ht-message.bot h3,
        .ht-message.bot h4 { margin: 10px 0 6px 0; font-size: 15px; font-weight: 700; color: #CC1111; }
        .ht-message.bot h1:first-child,
        .ht-message.bot h2:first-child,
        .ht-message.bot h3:first-child { margin-top: 0; }
        .ht-message.bot p { margin: 0 0 8px 0; }
        .ht-message.bot p:last-child { margin-bottom: 0; }
        .ht-message.bot ul,
        .ht-message.bot ol { margin: 6px 0 10px 0; padding-left: 20px; }
        .ht-message.bot li { margin-bottom: 4px; }
        .ht-message.bot code {
            font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
            background: rgba(204, 17, 17, 0.08);
            padding: 2px 5px;
            border-radius: 4px;
            font-size: 13px;
            color: #990000;
        }
        .ht-message.bot pre {
            background: rgba(204, 17, 17, 0.04);
            padding: 8px 12px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 8px 0;
            border: 1px solid rgba(204, 17, 17, 0.1);
        }
        .ht-message.bot pre code { background: none; padding: 0; font-size: 13px; }
        .ht-message.bot strong { font-weight: 700; color: #990000; }
        .ht-message.bot blockquote {
            border-left: 3px solid rgba(204, 17, 17, 0.35);
            padding-left: 10px;
            margin: 8px 0;
            color: #7a0000;
            font-style: italic;
        }

        /* ── Footer / Input Area ──────────────────────────────────────────── */
        .ht-chat-footer {
            padding: 10px;
            display: flex;
            gap: 8px;
            background: rgba(255, 255, 255, 0.5);
            border-top: 1px solid rgba(0, 0, 0, 0.05);
            align-items: flex-end;
        }
        #ht-chat-input {
            flex: 1;
            padding: 9px 12px;
            border: 1px solid #ccc;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
            resize: none;
            height: 38px;
            min-height: 38px;
            max-height: 120px;
            box-sizing: border-box;
            overflow-y: hidden;
            line-height: 1.4;
        }
        #ht-chat-input:focus {
            border-color: #CC1111;
            box-shadow: 0 0 0 2px rgba(204, 17, 17, 0.15);
        }
        #ht-chat-send {
            background: linear-gradient(135deg, #CC1111, #a80d0d);
            color: white;
            border: none;
            padding: 0 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            height: 38px;
            box-sizing: border-box;
            transition: background 0.2s, transform 0.1s;
            box-shadow: 0 2px 8px rgba(204, 17, 17, 0.3);
            letter-spacing: 0.3px;
        }
        #ht-chat-send:hover {
            background: linear-gradient(135deg, #aa0d0d, #8a0a0a);
            transform: translateY(-1px);
        }
        #ht-chat-send:active { transform: translateY(0); }
    </style>
    <?php
}


// ─────────────────────────────────────────────────────────────────────────────
// 4. JAVASCRIPT ENGINE: Connects frontend chat interactions to FastAPI
// ─────────────────────────────────────────────────────────────────────────────
add_action('wp_footer', 'ht_inject_chatbot_js', 99);
function ht_inject_chatbot_js() {
    if (!is_single() && !is_category()) return;
    ?>
    <!-- Load marked.js for Markdown rendering -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
    document.addEventListener('DOMContentLoaded', function () {
        const toggleBtn    = document.getElementById('ht-chat-toggle');
        const closeBtn     = document.getElementById('ht-chat-close');
        const chatWindow   = document.getElementById('ht-chat-window');
        const sendBtn      = document.getElementById('ht-chat-send');
        const chatInput    = document.getElementById('ht-chat-input');
        const msgContainer = document.getElementById('ht-chat-messages');

        // Maintain conversation context across messages
        const chatHistory = [];

        toggleBtn.addEventListener('click', () => {
            chatWindow.classList.toggle('ht-chat-hidden');
            if (!chatWindow.classList.contains('ht-chat-hidden')) {
                chatInput.focus();
                autoResizeInput();
            }
        });
        closeBtn.addEventListener('click', () => chatWindow.classList.add('ht-chat-hidden'));

        // Auto-resize textarea as the user types
        function autoResizeInput() {
            chatInput.style.height = 'auto';
            const borderHeight = chatInput.offsetHeight - chatInput.clientHeight;
            let newHeight = chatInput.scrollHeight + borderHeight;
            if (newHeight < 38) newHeight = 38;
            if (newHeight > 120) {
                chatInput.style.height = '120px';
                chatInput.style.overflowY = 'auto';
            } else {
                chatInput.style.height = newHeight + 'px';
                chatInput.style.overflowY = 'hidden';
            }
        }
        chatInput.addEventListener('input', autoResizeInput);

        async function sendMessage() {
            const text = chatInput.value.trim();
            if (!text) return;

            appendMessage(text, 'user');
            chatInput.value = '';
            autoResizeInput();

            const botMessageDiv = appendMessage('...', 'bot');

            chatHistory.push({ role: 'user', content: text });

            let accumulatedResponse = '';

            try {
                const response = await fetch('https://lms-chatbot-api.vercel.app/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-API-Key': 'test_key_123'
                    },
                    body: JSON.stringify({
                        lesson_id:    window.WP_CHAT_CONTEXT.lesson_id,
                        message:      text,
                        chat_history: chatHistory.slice(0, -1)
                    })
                });

                if (!response.ok) throw new Error("Connection failed");

                const reader  = response.body.getReader();
                const decoder = new TextDecoder();
                botMessageDiv.innerHTML = ''; // Clear loading dots

                let buffer = '';
                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop(); // Keep incomplete last line in buffer

                    for (const line of lines) {
                        const trimmedLine = line.trim();
                        if (!trimmedLine.startsWith('data: ')) continue;

                        let rawData = trimmedLine.slice(6);
                        if (rawData.trim() === '[DONE]') break;

                        let content = '';
                        try {
                            const parsed = JSON.parse(rawData);
                            content = parsed.token || '';
                        } catch (e) {
                            content = rawData; // Fallback for plain-text streams
                        }

                        accumulatedResponse += content;

                        if (window.marked && typeof window.marked.parse === 'function') {
                            botMessageDiv.innerHTML = window.marked.parse(accumulatedResponse);
                        } else {
                            botMessageDiv.textContent = accumulatedResponse;
                        }
                        msgContainer.scrollTop = msgContainer.scrollHeight;
                    }
                }

                chatHistory.push({ role: 'assistant', content: accumulatedResponse });

            } catch (err) {
                botMessageDiv.textContent = "Sorry, could not reach the server right now.";
            }
        }

        function appendMessage(text, sender) {
            const msg = document.createElement('div');
            msg.className = 'ht-message ' + sender;
            msg.innerText = text;
            msgContainer.appendChild(msg);
            msgContainer.scrollTop = msgContainer.scrollHeight;
            return msg;
        }

        sendBtn.addEventListener('click', sendMessage);

        // Enter = send, Shift+Enter = new line
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    });
    </script>
    <?php
}
