import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./motion.css";
import { initializeTheme } from "./theme";
import { initializeUiScale } from "./uiScale";

initializeTheme();
// Grow the interface on large screens so it never looks too small.
initializeUiScale();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
