/* Carga los scripts con un sello temporal para que, al recargar despues de
   actualizar, el navegador no sirva los datos viejos de su cache.
   async=false conserva el orden de ejecucion.
   Va en un archivo aparte (no en linea) para poder usar una CSP estricta. */
(function () {
  var sello = location.protocol === "file:" ? "" : "?v=" + Date.now();
  // Si la URL lleva ?cartera=<id>, lo añadimos a datos.js: la etiqueta <script>
  // no puede mandar cabeceras, así que la URL es el único canal para que el
  // servidor sepa qué cartera sirve como DATOS inicial (pestañas independientes).
  var cartera = new URLSearchParams(location.search).get("cartera");
  var sufijoCartera = cartera ? "&cartera=" + encodeURIComponent(cartera) : "";
  ["datos.js", "canal.js", "graficos.js", "app.js", "editor.js"].forEach(function (archivo) {
    var s = document.createElement("script");
    s.src = archivo + sello + (archivo === "datos.js" ? sufijoCartera : "");
    s.async = false;
    document.body.appendChild(s);
  });
})();
