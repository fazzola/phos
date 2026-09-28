/* PHOS local Swagger UI bootstrap. The renderer and API schema stay local. */
window.addEventListener("DOMContentLoaded", function () {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    presets: [SwaggerUIBundle.presets.apis],
    layout: "BaseLayout"
  });
});
