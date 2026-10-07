/* Carga los scripts con un sello temporal para que, al recargar despues de
   actualizar, el navegador no sirva los datos viejos de su cache.
   async=false conserva el orden de ejecucion.
   Va en un archivo aparte (no en linea) para poder usar una CSP estricta. */
(function () {
  var sello = location.protocol === "file:" ? "" : "?v=" + Date.now();
  /* Cartera anclada a esta pestaña (?cartera=<id>): un <script> no puede mandar
     cabeceras, asi que el id viaja en la URL de datos.js, que es la que trae el
     panel inicial. Las demas rutas lo leen de la direccion de la pagina. */
  var pin = new URLSearchParams(location.search).get("cartera") || "";
  ["datos.js", "canal.js", "graficos.js", "app.js", "editor.js"].forEach(function (archivo) {
    var s = document.createElement("script");
    var busca = sello;
    if (archivo === "datos.js" && pin) {
      busca += (busca ? "&" : "?") + "cartera=" + encodeURIComponent(pin);
    }
    s.src = archivo + busca;
    s.async = false;
    document.body.appendChild(s);
  });
})();
