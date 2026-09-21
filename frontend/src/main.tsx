import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { createApi } from "./api";
import "./theme.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App api={createApi()} />
  </React.StrictMode>,
);
