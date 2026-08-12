import { useState } from "react";

type Screen = "screensaver" | "menu";

function App() {
  const [screen, setScreen] = useState<Screen>("screensaver");

  if (screen === "screensaver") {
    return (
      <main
        style={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#f5f1eb",
          cursor: "pointer",
        }}
        onClick={() => setScreen("menu")}
      >
        <h1>화면을 터치해서 시작하세요</h1>
      </main>
    );
  }

  return (
    <main
      style={{
        // 임시 스타일
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#f5f1eb",
        color: "#111",
      }}
    >
      <section>
        <h1>MCM AI Lookbook</h1>
        <button onClick={() => setScreen("screensaver")}>
          처음 화면으로 돌아가기
        </button>
      </section>
    </main>
  );
}

export default App;