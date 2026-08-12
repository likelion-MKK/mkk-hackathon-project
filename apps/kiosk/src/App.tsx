import { useState } from "react";
import "./App.css";

type KioskScreen =
  | "screensaver" // S01
  | "menu" // S02
  | "consent" // S02 consent step
  | "calibration" // S03 preparation
  | "lookbook" // S03
  | "finalizing" // S03 → S04
  | "report"; // S04

type ProductCategory = "가방" | "백팩" | "지갑" | "전체 컬렉션";

type CategoryOption = {
  name: ProductCategory;
  englishName: string;
  number: string;
};

const productCategories: CategoryOption[] = [
  { name: "가방", englishName: "BAGS", number: "01" },
  { name: "백팩", englishName: "BACKPACKS", number: "02" },
  { name: "지갑", englishName: "SMALL LEATHER GOODS", number: "03" },
  { name: "전체 컬렉션", englishName: "ALL COLLECTION", number: "04" },
];

function BrandMark({ light = false }: { light?: boolean }) {
  return (
    <span className={`brand-mark${light ? " brand-mark--light" : ""}`}>
      <strong>MCM</strong>
      <span>MÜNCHEN · 1976</span>
    </span>
  );
}

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

function CategoryGlyph({ index }: { index: number }) {
  if (index === 0) {
    return (
      <svg aria-hidden="true" viewBox="0 0 140 112">
        <path d="M29 43h82l8 55H21l8-55Z" />
        <path d="M49 46c0-20 8-30 21-30s21 10 21 30" />
        <path d="M29 58h82" />
      </svg>
    );
  }

  if (index === 1) {
    return (
      <svg aria-hidden="true" viewBox="0 0 140 112">
        <path d="M37 39c0-14 11-25 25-25h16c14 0 25 11 25 25v60H37V39Z" />
        <path d="M37 49h66M50 67h40v22H50z" />
        <path d="M37 58c-10 8-13 21-10 38M103 58c10 8 13 21 10 38" />
      </svg>
    );
  }

  if (index === 2) {
    return (
      <svg aria-hidden="true" viewBox="0 0 140 112">
        <rect x="25" y="30" width="90" height="57" rx="3" />
        <path d="M25 43h90M78 54h37v22H78z" />
        <circle cx="88" cy="65" r="2" />
      </svg>
    );
  }

  return (
    <svg aria-hidden="true" viewBox="0 0 140 112">
      <circle cx="70" cy="56" r="38" />
      <circle cx="70" cy="56" r="25" />
      <path d="M70 18v76M32 56h76M43 29l54 54M97 29 43 83" />
    </svg>
  );
}

function ScreenHeader({
  step,
  label,
  light = false,
  onHome,
}: {
  step: string;
  label: string;
  light?: boolean;
  onHome: () => void;
}) {
  return (
    <header className={`screen-header${light ? " screen-header--light" : ""}`}>
      <button className="brand-button" type="button" onClick={onHome}>
        <BrandMark light={light} />
        <span className="sr-only">처음 화면으로 이동</span>
      </button>

      <div className="screen-progress" aria-label={`${step} ${label}`}>
        <span>{step}</span>
        <i aria-hidden="true" />
        <span>{label}</span>
      </div>
    </header>
  );
}

function Screensaver({ onStart }: { onStart: () => void }) {
  return (
    <main className="kiosk-screen screensaver" aria-labelledby="screensaver-title">
      <button
        className="screensaver__hit-area"
        type="button"
        onClick={onStart}
        aria-label="화면을 터치해 취향 발견 시작하기"
      />

      <div className="screensaver__grain" aria-hidden="true" />
      <div className="screensaver__halo" aria-hidden="true" />
      <div className="screensaver__orbit screensaver__orbit--one" aria-hidden="true" />
      <div className="screensaver__orbit screensaver__orbit--two" aria-hidden="true" />

      <div className="screensaver__monogram" aria-hidden="true">
        <span>M</span>
        <span>C</span>
        <span>M</span>
      </div>

      <header className="screensaver__header">
        <BrandMark light />
        <span className="screensaver__edition">AI LOOKBOOK EXPERIENCE</span>
      </header>

      <section className="screensaver__content">
        <p className="eyebrow eyebrow--light">A PRIVATE DISCOVERY</p>
        <h1 id="screensaver-title">
          <span>당신도 몰랐던</span>
          <strong>취향을 발견해보세요</strong>
        </h1>
        <p className="screensaver__description">
          짧은 룩북을 감상하면,
          <br />
          당신의 시선이 이끄는 MCM을 찾아드려요.
        </p>
      </section>

      <div className="touch-cue" aria-hidden="true">
        <span className="touch-cue__rings">
          <i />
          <b>
            <svg viewBox="0 0 32 32">
              <path d="M15.5 4.5a2.5 2.5 0 0 1 2.5 2.5v8.2l1.4-1.2a2.3 2.3 0 0 1 3.4.5l4 6.1c.8 1.2.9 2.6.4 3.9l-1.1 2.8H13.4l-4.8-7.7a2.4 2.4 0 0 1 .7-3.3 2.4 2.4 0 0 1 3.2.5l.5.7V7a2.5 2.5 0 0 1 2.5-2.5Z" />
            </svg>
          </b>
        </span>
        <span className="touch-cue__text">
          <strong>화면을 터치해 시작하세요</strong>
          <small>TOUCH TO DISCOVER</small>
        </span>
      </div>

      <div className="screensaver__footer" aria-hidden="true">
        <span>SEOUL · 2026</span>
        <span>PERSONAL STYLE JOURNEY</span>
      </div>
    </main>
  );
}

function CategoryMenu({
  onSelect,
  onHome,
}: {
  onSelect: (category: ProductCategory) => void;
  onHome: () => void;
}) {
  return (
    <main className="kiosk-screen experience-screen experience-screen--ivory">
      <ScreenHeader step="01" label="CATEGORY" onHome={onHome} />

      <section className="menu-layout" aria-labelledby="menu-title">
        <div className="menu-intro">
          <p className="eyebrow">CURATE YOUR JOURNEY</p>
          <h1 id="menu-title">
            어떤 취향부터
            <br />
            발견해볼까요?
          </h1>
          <p className="lead-copy">
            지금 가장 마음이 가는 카테고리를 선택해주세요.
            <br />
            당신의 시선으로 새로운 취향을 발견합니다.
          </p>

          <button className="text-button" type="button" onClick={onHome}>
            <span aria-hidden="true">←</span> 처음으로 돌아가기
          </button>
        </div>

        <div className="category-grid">
          {productCategories.map((category, index) => (
            <button
              className={`category-card category-card--${index + 1}`}
              key={category.name}
              type="button"
              onClick={() => onSelect(category.name)}
            >
              <span className="category-card__number">{category.number}</span>
              <span className="category-card__art">
                <CategoryGlyph index={index} />
              </span>
              <span className="category-card__copy">
                <strong>{category.name}</strong>
                <small>{category.englishName}</small>
              </span>
              <span className="category-card__arrow">
                <ArrowIcon />
              </span>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

function CameraConsent({
  category,
  onBack,
  onContinue,
  onHome,
}: {
  category: ProductCategory | null;
  onBack: () => void;
  onContinue: () => void;
  onHome: () => void;
}) {
  return (
    <main className="kiosk-screen experience-screen experience-screen--sand">
      <ScreenHeader step="02" label="PERMISSION" onHome={onHome} />

      <section className="consent-layout" aria-labelledby="consent-title">
        <div className="consent-visual" aria-hidden="true">
          <div className="consent-visual__frame">
            <span className="frame-corner frame-corner--tl" />
            <span className="frame-corner frame-corner--tr" />
            <span className="frame-corner frame-corner--bl" />
            <span className="frame-corner frame-corner--br" />
            <div className="consent-visual__lens">
              <i />
            </div>
            <span className="consent-visual__label">PRIVATE · ON DEVICE</span>
          </div>
        </div>

        <div className="consent-content">
          <p className="eyebrow">YOUR PRIVACY, FIRST</p>
          <h1 id="consent-title">
            당신의 시선은
            <br />
            순간만 머뭅니다.
          </h1>
          <p className="lead-copy">
            <strong>{category ?? "선택한 카테고리"}</strong> 룩북을 감상하는 동안
            카메라로 시선과 표정 관련 신호를 분석합니다.
          </p>

          <div className="privacy-note">
            <span className="privacy-note__icon">
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <rect x="5" y="10" width="14" height="10" rx="2" />
                <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v2" />
              </svg>
            </span>
            <span>
              <strong>원본 영상은 저장하지 않아요.</strong>
              <small>분석된 파생 신호만 현재 추천을 위해 처리합니다.</small>
            </span>
          </div>

          <div className="action-row">
            <button className="button button--secondary" type="button" onClick={onBack}>
              동의하지 않음
            </button>
            <button className="button button--primary" type="button" onClick={onContinue}>
              동의하고 계속 <ArrowIcon />
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

function Calibration({ onHome }: { onHome: () => void }) {
  return (
    <main className="kiosk-screen experience-screen calibration-screen">
      <ScreenHeader step="03" label="CALIBRATION" light onHome={onHome} />

      <section className="calibration-layout" aria-labelledby="calibration-title">
        <div className="calibration-copy">
          <p className="eyebrow eyebrow--light">FOLLOW THE LIGHT</p>
          <h1 id="calibration-title">
            시선을
            <br />
            맞춰볼게요.
          </h1>
          <p>
            화면에서 천천히 움직이는 빛을
            <br />
            고개는 편안히 둔 채 눈으로 따라가세요.
          </p>

          <span className="preview-badge">CALIBRATION PREVIEW</span>
          <button className="text-button text-button--light" type="button" onClick={onHome}>
            <span aria-hidden="true">←</span> 처음으로 돌아가기
          </button>
        </div>

        <div className="calibration-stage" aria-hidden="true">
          <div className="calibration-stage__grid" />
          <svg className="calibration-stage__path" viewBox="0 0 620 500">
            <path d="M80 88 C260 24 382 170 530 102 S512 312 348 254 S132 228 94 405 C210 470 404 430 540 382" />
          </svg>
          <span className="anchor anchor--one" />
          <span className="anchor anchor--two" />
          <span className="anchor anchor--three" />
          <span className="anchor anchor--four" />
          <span className="gaze-target">
            <i />
          </span>
          <span className="calibration-stage__caption">KEEP YOUR HEAD STILL · FOLLOW WITH YOUR EYES</span>
        </div>
      </section>
    </main>
  );
}

function App() {
  const [screen, setScreen] = useState<KioskScreen>("screensaver");
  const [selectedCategory, setSelectedCategory] = useState<ProductCategory | null>(null);

  const selectCategory = (category: ProductCategory) => {
    setSelectedCategory(category);
    setScreen("consent");
  };

  const restart = () => {
    setSelectedCategory(null);
    setScreen("screensaver");
  };

  if (screen === "screensaver") {
    return <Screensaver onStart={() => setScreen("menu")} />;
  }

  if (screen === "menu") {
    return <CategoryMenu onSelect={selectCategory} onHome={restart} />;
  }

  if (screen === "consent") {
    return (
      <CameraConsent
        category={selectedCategory}
        onBack={() => {
          setSelectedCategory(null);
          setScreen("menu");
        }}
        onContinue={() => setScreen("calibration")}
        onHome={restart}
      />
    );
  }

  if (screen === "calibration") {
    return <Calibration onHome={restart} />;
  }

  return (
    <main className="kiosk-screen placeholder-screen">
      <BrandMark />
      <p>다음 화면을 준비 중입니다.</p>
    </main>
  );
}

export default App;
