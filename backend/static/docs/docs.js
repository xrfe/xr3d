(() => {
  const explorer = document.getElementById("swagger-ui");
  const root = explorer || document.getElementById("redoc");
  const styles = getComputedStyle(document.documentElement);
  const token = (name) => styles.getPropertyValue(`--${name}`).trim();

  const showError = () => {
    const message = document.createElement("p");
    message.className = "docs-error";
    message.setAttribute("role", "alert");
    message.append("The documentation could not load. ");
    const link = document.createElement("a");
    link.href = root.dataset.spec;
    link.textContent = "OpenAPI JSON";
    message.append(link);
    root.replaceChildren(message);
  };

  if (explorer && typeof window.SwaggerUIBundle === "function") {
    const swagger = window.SwaggerUIBundle;
    window.ui = swagger({
      dom_id: "#swagger-ui",
      url: root.dataset.spec,
      oauth2RedirectUrl: new URL(root.dataset.oauthRedirect, location.origin).href,
      layout: "BaseLayout",
      deepLinking: true,
      showExtensions: true,
      showCommonExtensions: true,
      validatorUrl: null,
      presets: [swagger.presets.apis, swagger.SwaggerUIStandalonePreset],
    });
  } else if (!explorer && window.Redoc) {
    window.Redoc.init(root.dataset.spec, {
      disableTelemetry: true,
      scrollYOffset: "#studio-header",
      theme: {
        colors: {
          primary: { main: token("accent") },
          text: { primary: token("text"), secondary: token("muted") },
          success: { main: token("success") },
          warning: { main: token("warning") },
          error: { main: token("danger") },
          border: { dark: token("border"), light: token("border") },
        },
        typography: {
          fontFamily: token("font"),
          fontSize: "15px",
          headings: { fontFamily: token("font"), fontWeight: "600" },
          code: { fontFamily: token("mono"), color: token("text"), backgroundColor: token("surface-raised") },
          links: { color: token("accent"), hover: token("text"), visited: token("accent") },
        },
        sidebar: {
          backgroundColor: token("surface"),
          textColor: token("muted"),
          activeTextColor: token("accent"),
          groupItems: { activeBackgroundColor: token("surface-raised") },
          level1Items: { activeBackgroundColor: token("surface-raised") },
          arrow: { color: token("muted") },
        },
        rightPanel: {
          backgroundColor: token("surface"),
          textColor: token("text"),
          servers: {
            overlay: { backgroundColor: token("surface"), textColor: token("text") },
            url: { backgroundColor: token("surface-raised") },
          },
        },
        codeBlock: { backgroundColor: token("surface-raised") },
        schema: { linesColor: token("border"), nestedBackground: token("surface"), typeNameColor: token("accent") },
        fab: { backgroundColor: token("surface-raised"), color: token("accent") },
      },
    }, root, (error) => { if (error) showError(); });
  } else {
    showError();
  }
})();
