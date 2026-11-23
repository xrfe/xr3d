"""XR3D documentation pages using the backend's existing OpenAPI schema."""
from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse

from backend.config import settings

router = APIRouter(include_in_schema=False)
ASSETS = Path(__file__).resolve().parents[1] / "static" / "docs"
SWAGGER = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.0"
REDOC = "https://cdn.jsdelivr.net/npm/redoc@2.5.3/bundles/redoc.standalone.js"


def docs_page(request: Request, explorer: bool) -> HTMLResponse:
    def route(name: str, **params: str) -> str:
        return escape(request.url_for(name, **params).path, quote=True)

    logo = route("docs_assets", path="app_icon.png")
    style = route("docs_assets", path="docs.css")
    script = route("docs_assets", path="docs.js")
    swagger_path = route("swagger_docs")
    reference_path = route("reference_docs")
    openapi_path = route("openapi")
    oauth_redirect = route("swagger_oauth_redirect")
    explorer_current = ' aria-current="page"' if explorer else ""
    reference_current = ' aria-current="page"' if not explorer else ""
    page = "API Explorer" if explorer else "API Reference"
    target = "swagger-ui" if explorer else "redoc"
    library_css = f'<link rel="stylesheet" href="{SWAGGER}/swagger-ui.css">' if explorer else ""
    library_js = f"{SWAGGER}/swagger-ui-bundle.js" if explorer else REDOC
    return HTMLResponse(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>XR3D · {page}</title>
  <link rel="icon" href="{logo}" type="image/png">
  {library_css}
  <link rel="stylesheet" href="{style}">
  <script defer src="{library_js}"></script>
  <script defer src="{script}"></script>
</head>
<body>
  <a class="skip-link" href="#api-docs">Skip to API documentation</a>
  <header class="studio-header" id="studio-header">
    <div class="studio-header-inner">
      <a class="studio-brand" href="{swagger_path}">
        <img src="{logo}" alt="" width="36" height="36">
        <span>XR3D</span>
      </a>
      <nav aria-label="API documentation">
        <a href="{swagger_path}"{explorer_current}>API Explorer</a>
        <a href="{reference_path}"{reference_current}>API Reference</a>
      </nav>
    </div>
  </header>
  <main id="api-docs" aria-label="{page}">
    <noscript>Enable JavaScript to use the API documentation. <a href="{openapi_path}">OpenAPI JSON</a></noscript>
    <div id="{target}" data-spec="{openapi_path}" data-oauth-redirect="{oauth_redirect}"></div>
  </main>
</body>
</html>""")


@router.get(f"{settings.API_PREFIX}/docs", response_class=HTMLResponse)
async def swagger_docs(request: Request):
    return docs_page(request, explorer=True)


@router.get("/redoc", response_class=HTMLResponse)
async def reference_docs(request: Request):
    return docs_page(request, explorer=False)


@router.get("/docs/oauth2-redirect", response_class=HTMLResponse)
async def swagger_oauth_redirect():
    return get_swagger_ui_oauth2_redirect_html()
