"""
Browser-based API client for bypassing Cloudflare bot detection.
This is a fallback when direct HTTP requests are blocked.
"""
import json
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def openai_chat_with_browser(messages: list[dict[str, str]], model: str, api_key: str, base_url: str) -> Iterable[str]:
    """
    Use undetected-chromedriver to call API through a real browser.
    This is SLOW (3-5 seconds overhead) but bypasses Cloudflare detection.
    """
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        raise RuntimeError("undetected-chromedriver not installed. Run: pip install undetected-chromedriver")

    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = None
    try:
        driver = uc.Chrome(options=options, version_main=None)

        # Inject fetch script
        script = f"""
        return fetch('{base_url}/v1/chat/completions', {{
            method: 'POST',
            headers: {{
                'Authorization': 'Bearer {api_key}',
                'Content-Type': 'application/json'
            }},
            body: JSON.stringify({{
                model: '{model}',
                messages: {json.dumps(messages)},
                stream: false
            }})
        }}).then(r => r.json());
        """

        # Navigate to the domain first to get cookies
        driver.get(base_url)

        # Execute the API call
        result = driver.execute_script(script)

        if isinstance(result, dict):
            if "error" in result:
                error_msg = result.get("error", {}).get("message", str(result))
                raise RuntimeError(f"API error: {error_msg}")

            # Extract response
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                # Yield in chunks to simulate streaming
                for i in range(0, len(content), 20):
                    yield content[i:i+20]
            else:
                raise RuntimeError("No response from API")
        else:
            raise RuntimeError(f"Unexpected response type: {type(result)}")

    except Exception as e:
        logger.exception("Browser API call failed")
        raise RuntimeError(f"Browser API call failed: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.warning("Failed to quit browser driver: %s", e)
