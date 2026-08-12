import { useState } from "react";

type KioskScreen =
  | "screensaver" // S01
  | "menu" // S02
  | "consent" // S02 consent step
  | "calibration" // S03 preparation
  | "lookbook" // S03
  | "finalizing" // S03 → S04
  | "report"; // S04

type ProductCategory = "가방" | "백팩" | "지갑" | "전체 컬렉션";

const productCategories: ProductCategory[] = [
  "가방",
  "백팩",
  "지갑",
  "전체 컬렉션",
];

const pageStyle = {
  minHeight: "100vh",
  display: "grid",
  placeItems: "center",
  padding: "24px",
  textAlign: "center" as const,
};

const buttonStyle = {
  padding: "16px 24px",
  fontSize: "18px",
  cursor: "pointer",
};

function App() {
  const [screen, setScreen] = useState<KioskScreen>("screensaver");
  const [selectedCategory, setSelectedCategory] =
    useState<ProductCategory | null>(null);

  const selectCategory = (category: ProductCategory) => {
    setSelectedCategory(category);
    setScreen("consent");
  };

  const restart = () => {
    setSelectedCategory(null);
    setScreen("screensaver");
  };

  if (screen === "screensaver") {
    return (
      <main
        style={{
          ...pageStyle,
          background: "#151515",
          color: "white",
        }}
      >
        <section style={{ maxWidth: "680px" }}>
          <h1>당신도 몰랐던 취향을 발견해보세요</h1>
          <p>
            짧은 룩북을 감상하면 당신의 시선이 이끄는 MCM을
            찾아드려요.
          </p>

          <button
            type="button"
            style={{ ...buttonStyle, marginTop: "24px" }}
            onClick={() => setScreen("menu")}
          >
            취향 발견하기
          </button>
        </section>
      </main>
    );
  }

  if (screen === "menu") {
    return (
      <main
        style={{
          ...pageStyle,
          background: "#f5f1eb",
          color: "#111",
        }}
      >
        <section>
          <h1>어떤 취향부터 발견해볼까요?</h1>
          <p>관심 있는 카테고리를 선택해주세요.</p>

          <div
            style={{
              display: "grid",
              gap: "12px",
              marginTop: "24px",
            }}
          >
            {productCategories.map((category) => (
              <button
                key={category}
                type="button"
                style={buttonStyle}
                onClick={() => selectCategory(category)}
              >
                {category}
              </button>
            ))}

            <button
              type="button"
              style={buttonStyle}
              onClick={restart}
            >
              처음으로
            </button>
          </div>
        </section>
      </main>
    );
  }

  if (screen === "consent") {
    return (
      <main
        style={{
          ...pageStyle,
          background: "white",
          color: "#111",
        }}
      >
        <section style={{ maxWidth: "600px" }}>
          <h1>카메라 이용 동의</h1>
          <p>
            {selectedCategory} 룩북을 감상하는 동안 카메라로 시선과 표정
            관련 신호를 분석합니다.
          </p>
          <p>
            웹캠 원본 영상은 저장하지 않으며, 분석된 파생 신호만
            처리합니다.
          </p>

          <div
            style={{
              display: "flex",
              justifyContent: "center",
              gap: "12px",
              marginTop: "24px",
            }}
          >
            <button
              type="button"
              style={buttonStyle}
              onClick={() => {
                setSelectedCategory(null);
                setScreen("menu");
              }}
            >
              동의하지 않음
            </button>

            <button
              type="button"
              style={buttonStyle}
              onClick={() => setScreen("calibration")}
            >
              동의하고 계속
            </button>
          </div>
        </section>
      </main>
    );
  }

  if (screen === "calibration") {
    return (
      <main style={pageStyle}>
        <section>
          <h1>시선 보정</h1>
          <p>화면의 안내에 따라 움직이는 점을 바라봐주세요.</p>
          <p>실제 시선 보정 기능은 다음 단계에서 구현합니다.</p>

          <button type="button" style={buttonStyle} onClick={restart}>
            처음으로 돌아가기
          </button>
        </section>
      </main>
    );
  }

  return (
    <main style={pageStyle}>
      <p>다음 화면을 준비 중입니다.</p>
    </main>
  );
}

export default App;
