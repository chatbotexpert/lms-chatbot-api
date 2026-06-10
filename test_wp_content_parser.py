"""
test_wp_content_parser.py
--------------------------
Converts WordPress Gutenberg block-editor content (raw post_content) to
clean plain text using the `html2text` library, then builds the exact
JSON payload expected by the FastAPI /api/ingest endpoint.

Libraries used
--------------
- html2text   : converts HTML -> plain text, preserves image URLs automatically
- re          : strips Gutenberg block-comment markers before parsing

Run with:
    python -X utf8 test_wp_content_parser.py
"""

import sys
import re
import json
import html2text          # pip install html2text

# Force UTF-8 so Spanish characters display correctly in Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# ---------------------------------------------------------------------------
# Core conversion function
# ---------------------------------------------------------------------------

def wp_blocks_to_text(raw_content: str) -> str:
    """
    Convert WordPress Gutenberg block-editor HTML (post_content) to plain text.

    Uses html2text under the hood, which handles:
      - Stripping HTML tags
      - Preserving image URLs as  [Image: URL]
      - Decoding HTML entities automatically

    Parameters
    ----------
    raw_content : str
        Raw WordPress post_content (may contain Gutenberg block comments,
        HTML tags, escaped characters like \\n, \\/, \\").

    Returns
    -------
    str
        Clean, human-readable plain text with image URLs at their original
        position in the content hierarchy.
    """

    text = raw_content

    # Step 1 — Unescape WordPress / JSON escape sequences so we get real HTML
    text = text.replace('\\n', '\n')   # \n  -> newline
    text = text.replace('\\/', '/')    # \/  -> /
    text = text.replace('\\"', '"')    # \"  -> "

    # Step 2 — Remove Gutenberg <!-- wp:... --> block comment markers
    #           (they are not HTML and html2text would leave them in)
    text = re.sub(r'<!--\s*\/?wp:[^>]*-->', '', text)

    # Step 3 — Configure html2text
    converter = html2text.HTML2Text()
    converter.ignore_links      = True   # don't keep <a href> links
    converter.ignore_emphasis   = True   # strip **bold** and _italic_ markers
    converter.body_width        = 0      # no line-wrapping
    converter.images_as_html    = False  # we'll handle images ourselves below

    # Step 4 — Replace <img src="..."> with a clean [Image: URL] marker BEFORE
    #           passing to html2text, so the URL is preserved at the right place.
    def _img_placeholder(m: re.Match) -> str:
        src = re.search(r'src=["\']([^"\']+)["\']', m.group(0))
        return f'\n[Image: {src.group(1)}]\n' if src else ''

    text = re.sub(r'<img[^>]+>', _img_placeholder, text, flags=re.IGNORECASE)

    # Step 5 — Let html2text handle all the remaining HTML
    text = converter.handle(text)

    # Step 6 — Tidy up: strip extra blank lines and leading/trailing whitespace
    lines  = [line.strip() for line in text.splitlines()]
    text   = '\n'.join(lines).strip()
    text   = re.sub(r'\n{3,}', '\n\n', text)

    return text


def extract_image_urls(raw_content: str) -> list[str]:
    """
    Extract all <img src="..."> URLs from raw WordPress post_content.

    Returns a deduplicated list of URLs in the order they appear.
    """
    # Unescape first so the regex can find clean src= attributes
    text = raw_content.replace('\\n', '\n').replace('\\/', '/').replace('\\"', '"')
    urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', text, flags=re.IGNORECASE)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


# ---------------------------------------------------------------------------
# Main transformer: WordPress post dict  →  FastAPI /api/ingest payload
# ---------------------------------------------------------------------------

def wp_post_to_ingest_payload(wp_post: dict) -> dict:
    """
    Transform a raw WordPress post object (as exported from the DB or REST API)
    into the exact JSON payload expected by POST /api/ingest.

    Mapping
    -------
    wp_post["ID"]           -> lesson_id     (prefixed with "lesson_")
    wp_post["post_author"]  -> instructor_id (prefixed with "instructor_")
    wp_post["post_content"] -> content       (converted to plain text)
    <img src> URLs          -> image_urls    (extracted list, deduplicated)

    Parameters
    ----------
    wp_post : dict
        A single WordPress post object (all string values, as exported).

    Returns
    -------
    dict
        Ready-to-POST payload for /api/ingest.
    """
    raw_content = wp_post.get("post_content", "")

    return {
        "lesson_id":     f"lesson_{wp_post['ID']}",
        "instructor_id": f"instructor_{wp_post['post_author']}",
        "content":       wp_blocks_to_text(raw_content),
        "image_urls":    extract_image_urls(raw_content),
    }


# ---------------------------------------------------------------------------
# Test / demo  —  uses the exact WordPress post JSON you provided
# ---------------------------------------------------------------------------

SAMPLE_WP_POST = {
    "ID": "2967",
    "post_author": "1",
    "post_date": "2026-05-22 13:20:20",
    "post_date_gmt": "2026-05-22 13:20:20",
    "post_content": "<!-- wp:heading -->\n<h2 class=\"wp-block-heading\">Objetivos<\/h2>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p>-Practicar con los pronombres de objeto directo e indirecto.<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:paragraph -->\n<p>-Revisar la conjugación y uso del Pretérito Imperfecto.<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:heading -->\n<h2 class=\"wp-block-heading\">Páginas: Ele book y Libro de Actividades<\/h2>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p><strong>Libro de actividades:<\/strong>&nbsp;páginas 38 (ejercicio 3) y 43<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:heading -->\n<h2 class=\"wp-block-heading\">Los deberes<\/h2>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p><strong>Libro de actividades:<\/strong>&nbsp;página 38, ejercicios 1, 2 y 4<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:paragraph -->\n<p><strong>Deberes extra:<\/strong>&nbsp;Escribir un texto sobre cómo era tu vida cuando tenías 18 años. Usamos el Pretérito Imperfecto.<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:heading -->\n<h2 class=\"wp-block-heading\">Resumen de la clase<\/h2>\n<!-- \/wp:heading -->\n\n<!-- wp:image {\"id\":2968,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-1.jpg\" alt=\"\" class=\"wp-image-2968\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:heading {\"level\":3} -->\n<h3 class=\"wp-block-heading\">Hola, chicos. ¿Qué tal estáis? Espero que muy bien. En la clase de ayer trabajasteis mucho y muy bien. Revisamos los pronombres de objeto directo e indirecto y también el Pretérito Imperfecto al final de la clase.<\/h3>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p>Aquí tenéis el resumen:<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:heading {\"level\":3} -->\n<h3 class=\"wp-block-heading\">Corrección de deberes<\/h3>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p>-Corregimos los deberes en la página 34 del libro de actividades:<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:image {\"id\":2969,\"sizeSlug\":\"large\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-large\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-2-1024x363.webp\" alt=\"\" class=\"wp-image-2969\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:image {\"id\":2970,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-3.webp\" alt=\"\" class=\"wp-image-2970\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:heading {\"level\":3} -->\n<h3 class=\"wp-block-heading\">Revisión del uso de los pronombres de objeto directo e indirecto<\/h3>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p>-Revisamos los pronombres y practicamos con los ejercicios en las fotocopias extra:<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:image {\"id\":2971,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-4.png\" alt=\"\" class=\"wp-image-2971\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:image {\"id\":2972,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-5.png\" alt=\"\" class=\"wp-image-2972\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:image {\"id\":2973,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-6.webp\" alt=\"\" class=\"wp-image-2973\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:image {\"id\":2974,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-7.webp\" alt=\"\" class=\"wp-image-2974\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:image {\"id\":2975,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-8.png\" alt=\"\" class=\"wp-image-2975\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:paragraph -->\n<p>Y también completamos en parejas el ejercicio 3 en la página 38 del libro de actividades:<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:image {\"id\":2976,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-9.png\" alt=\"\" class=\"wp-image-2976\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:heading {\"level\":3} -->\n<h3 class=\"wp-block-heading\">Revisamos el Pretérito Imperfecto<\/h3>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p>-Revisamos la conjugación y el uso del Pretérito Imperfecto:<\/p>\n<!-- \/wp:paragraph -->\n\n<!-- wp:image {\"id\":2977,\"sizeSlug\":\"full\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-full\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-10.webp\" alt=\"\" class=\"wp-image-2977\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:image {\"id\":2978,\"sizeSlug\":\"large\",\"linkDestination\":\"none\"} -->\n<figure class=\"wp-block-image size-large\"><img src=\"https:\/\/howtoselfhost.com\/wp-content\/uploads\/2026\/05\/spanish-11-714x1024.jpg\" alt=\"\" class=\"wp-image-2978\"\/><\/figure>\n<!-- \/wp:image -->\n\n<!-- wp:heading {\"level\":3} -->\n<h3 class=\"wp-block-heading\">Continuamos practicando el Pretérito Imperfecto en nuestra última clase el próximo martes.<\/h3>\n<!-- \/wp:heading -->\n\n<!-- wp:heading {\"level\":3} -->\n<h3 class=\"wp-block-heading\">¡Buena semana!<\/h3>\n<!-- \/wp:heading -->\n\n<!-- wp:heading {\"level\":3} -->\n<h3 class=\"wp-block-heading\">Andrea<\/h3>\n<!-- \/wp:heading -->\n\n<!-- wp:paragraph -->\n<p><\/p>\n<!-- \/wp:paragraph -->",
    "post_title": "A2 Booster-Lección 4 (19/5/2026) \"Nosotros se los damos\"",
    "post_status": "publish",
    "post_author": "1",
    "post_type": "post"
}


def run_tests():
    print("=" * 60)
    print("TEST: wp_post_to_ingest_payload()")
    print("=" * 60)

    payload = wp_post_to_ingest_payload(SAMPLE_WP_POST)

    print("\n--- FastAPI /api/ingest payload (JSON) ---\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    print("\n--- Assertions ---")

    # Field structure
    assert payload["lesson_id"]     == "lesson_2967",     "FAIL: lesson_id wrong"
    assert payload["instructor_id"] == "instructor_1",    "FAIL: instructor_id wrong"
    assert isinstance(payload["content"], str),           "FAIL: content not a string"
    assert isinstance(payload["image_urls"], list),       "FAIL: image_urls not a list"

    # Content quality
    assert "<"       not in payload["content"], "FAIL: HTML tags still in content"
    assert "&nbsp;"  not in payload["content"], "FAIL: HTML entity still in content"
    assert "Objetivos"             in payload["content"], "FAIL: heading missing"
    assert "Pretérito Imperfecto"  in payload["content"], "FAIL: Spanish text missing"

    # Image URLs
    assert len(payload["image_urls"]) == 11, \
        f"FAIL: expected 11 image URLs, got {len(payload['image_urls'])}"
    assert "https://howtoselfhost.com/wp-content/uploads/2026/05/spanish-1.jpg"          in payload["image_urls"], "FAIL: spanish-1 missing"
    assert "https://howtoselfhost.com/wp-content/uploads/2026/05/spanish-11-714x1024.jpg" in payload["image_urls"], "FAIL: spanish-11 missing"

    print(f"lesson_id     : {payload['lesson_id']}")
    print(f"instructor_id : {payload['instructor_id']}")
    print(f"image_urls    : {len(payload['image_urls'])} URLs found")
    print(f"content length: {len(payload['content'])} characters")
    print("\nAll assertions passed [OK]")


if __name__ == "__main__":
    run_tests()
