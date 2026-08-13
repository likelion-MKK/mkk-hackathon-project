import { useEffect, useState } from "react";
import bagImage from "./assets/categories/category-bags.png";
import apparelImage from "./assets/categories/category-apparel.png";
import accessoryImage from "./assets/categories/category-accessories.png";
import screensaverImageOne from "./assets/categories/screensaver-01.jpg";
import screensaverImageTwo from "./assets/categories/screensaver-02.jpg";
import screensaverImageThree from "./assets/categories/screensaver-03.jpg";
import "./App.css";

type KioskScreen =
  | "screensaver" // S01
  | "menu" // S02
  | "consent" // S02 consent step
  | "calibration" // S03 preparation
  | "lookbook" // S03
  | "finalizing" // S03 → S04
  | "report"; // S04

type ProductCategory = "가방" | "의류" | "액세서리" | "전체 컬렉션";

type CategoryOption = {
  name: ProductCategory;
  englishName: string;
  number: string;
  description: string;
};

const productCategories: CategoryOption[] = [
  {
    name: "가방",
    englishName: "BAGS",
    number: "01",
    description: "아이코닉 백과 데일리 백",
  },
  {
    name: "의류",
    englishName: "READY-TO-WEAR",
    number: "02",
    description: "새로운 시즌의 룩",
  },
  {
    name: "액세서리",
    englishName: "ACCESSORIES",
    number: "03",
    description: "스타일을 완성하는 디테일",
  },
  {
    name: "전체 컬렉션",
    englishName: "VIEW ALL",
    number: "04",
    description: "모든 카테고리에서 발견하기",
  },
];

const screensaverImages = [
  screensaverImageOne,
  screensaverImageTwo,
  screensaverImageThree,
];

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M4 12h15M14 6l6 6-6 6" />
    </svg>
  );
}

function Wordmark({ light = false }: { light?: boolean }) {
  return <span className={`wordmark${light ? " wordmark--light" : ""}`}>MCM</span>;
}

function StoreChrome({
  onHome,
  step,
  overlay = false,
}: {
  onHome: () => void;
  step?: string;
  overlay?: boolean;
}) {
  return (
    <>
      <div className="announcement-bar">
        <span>MCM AI LOOKBOOK</span>
        <span>당신의 시선으로 발견하는 새로운 스타일</span>
        <span>SEOUL · KO</span>
      </div>

      <header className={`store-header${overlay ? " store-header--overlay" : ""}`}>
        <nav className="store-nav" aria-label="카테고리 안내">
          <span>신상품</span>
          <span>가방</span>
          <span>의류</span>
          <span>액세서리</span>
        </nav>

        <button className="wordmark-button" type="button" onClick={onHome}>
          <Wordmark light={overlay} />
          <span className="sr-only">처음 화면으로 이동</span>
        </button>

        <div className="store-meta">
          <span>AI DISCOVERY</span>
          {step && <span>{step} / 03</span>}
        </div>
      </header>
    </>
  );
}

function Screensaver({ onStart }: { onStart: () => void }) {
  const [activeSlide, setActiveSlide] = useState(0);

  useEffect(() => {
    const slideTimer = window.setInterval(() => {
      setActiveSlide((currentSlide) => (currentSlide + 1) % screensaverImages.length);
    }, 5000);

    return () => window.clearInterval(slideTimer);
  }, []);

  return (
    <main className="store-screen screensaver screen-enter" aria-labelledby="screensaver-title">
      <button
        className="screensaver__hit-area"
        type="button"
        onClick={onStart}
        aria-label="화면을 터치해 취향 발견 시작하기"
      />

      <div className="screensaver__media" aria-hidden="true">
        {screensaverImages.map((image, index) => (
          <img
            className={index === activeSlide ? "is-active" : undefined}
            key={image}
            src={image}
            alt=""
          />
        ))}
      </div>

      <StoreChrome onHome={onStart} overlay />

      <section className="screensaver__copy">
        <p className="section-label">MCM AI LOOKBOOK</p>
        <h1 id="screensaver-title">
          당신도 몰랐던 취향을
          <br />
          발견해보세요
        </h1>
        <p className="screensaver__description">
          짧은 룩북을 감상하면 당신의 시선이 이끄는 스타일을 찾아드려요.
        </p>
        <span className="hero-cta">
          화면을 터치해 시작하기 <ArrowIcon />
        </span>
      </section>

      <div className="screensaver__index" aria-hidden="true">
        <span>{String(activeSlide + 1).padStart(2, "0")}</span>
        <i />
        <span>PERSONAL STYLE DISCOVERY</span>
      </div>
    </main>
  );
}

function CategoryMedia({ index }: { index: number }) {
  if (index === 0) {
    return <img className="category-card__image category-card__image--bag" src={bagImage} alt="" />;
  }

  if (index === 1) {
    return <img className="category-card__image category-card__image--apparel" src={apparelImage} alt="" />;
  }

  if (index === 2) {
    return (
      <img
        className="category-card__image category-card__image--accessory"
        src={accessoryImage}
        alt=""
      />
    );
  }

  return (
    <div className="collection-collage">
      <img src={apparelImage} alt="" />
      <img src={bagImage} alt="" />
    </div>
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
    <main className="store-screen gallery-screen screen-enter">
      <StoreChrome onHome={onHome} step="01" />

      <section className="gallery-heading" aria-labelledby="menu-title">
        <div>
          <p className="section-label">CHOOSE A CATEGORY</p>
          <h1 id="menu-title">어떤 스타일을 발견해볼까요?</h1>
        </div>
        <p>
          지금 가장 마음이 가는 카테고리를 선택해주세요.
          <br />
          선택한 컬렉션으로 룩북을 시작합니다.
        </p>
      </section>

      <section className="category-gallery" aria-label="상품 카테고리">
        {productCategories.map((category, index) => (
          <button
            className="category-card"
            key={category.name}
            type="button"
            onClick={() => onSelect(category.name)}
          >
            <span className="category-card__media">
              <CategoryMedia index={index} />
              <span className="category-card__number">{category.number}</span>
            </span>
            <span className="category-card__details">
              <span>
                <strong>{category.name}</strong>
                <small>{category.englishName}</small>
              </span>
              <span className="category-card__description">{category.description}</span>
              <span className="category-card__arrow">
                <ArrowIcon />
              </span>
            </span>
          </button>
        ))}
      </section>

      <button className="back-link" type="button" onClick={onHome}>
        ← 처음으로
      </button>
    </main>
  );
}

function ConsentMedia({ category }: { category: ProductCategory | null }) {
  if (category === "의류") {
    return <img src={apparelImage} alt="검정 재킷과 코냑 팬츠를 입은 패션 모델" />;
  }

  if (category === "액세서리") {
    return <img className="consent-accessory-image" src={accessoryImage} alt="MCM 가방과 참 액세서리" />;
  }

  if (category === "전체 컬렉션") {
    return (
      <div className="consent-collection">
        <img src={apparelImage} alt="패션 모델" />
        <img src={bagImage} alt="MCM 패턴 가방" />
      </div>
    );
  }

  return <img src={bagImage} alt="MCM 패턴 가방" />;
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
    <main className="store-screen consent-screen screen-enter">
      <StoreChrome onHome={onHome} step="02" />

      <section className="consent-page" aria-labelledby="consent-title">
        <div className="consent-page__media">
          <ConsentMedia category={category} />
          <span>SELECTED · {category ?? "COLLECTION"}</span>
        </div>

        <div className="consent-page__content">
          <p className="section-label">CAMERA PERMISSION</p>
          <h1 id="consent-title">
            카메라 사용에
            <br />
            동의해주세요
          </h1>
          <p className="consent-page__lead">
            <strong>{category ?? "선택한 카테고리"}</strong> 룩북을 감상하는 동안
            시선과 표정 관련 신호를 분석해 관심 있는 스타일을 찾습니다.
          </p>

          <dl className="privacy-list">
            <div>
              <dt>01</dt>
              <dd>
                <strong>원본 영상을 저장하지 않습니다</strong>
                <span>카메라 프레임은 기기 안에서만 일시적으로 처리됩니다.</span>
              </dd>
            </div>
            <div>
              <dt>02</dt>
              <dd>
                <strong>분석된 신호만 사용합니다</strong>
                <span>현재 세션의 추천을 위한 파생 신호만 처리합니다.</span>
              </dd>
            </div>
          </dl>

          <div className="consent-actions">
            <button className="store-button store-button--outline" type="button" onClick={onBack}>
              동의하지 않음
            </button>
            <button className="store-button store-button--solid" type="button" onClick={onContinue}>
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
    <main className="store-screen calibration-screen screen-enter">
      <StoreChrome onHome={onHome} step="03" />

      <section className="calibration-page" aria-labelledby="calibration-title">
        <div className="calibration-page__copy">
          <p className="section-label">EYE CALIBRATION</p>
          <h1 id="calibration-title">
            <span>움직이는 점을</span>
            <span>눈으로 따라가세요</span>
          </h1>
          <p>
            고개는 편안하게 두고 화면 위의 검은 점만 바라봐주세요.
            실제 시선 보정 기능은 다음 개발 단계에서 연결됩니다.
          </p>
          <span className="preview-label">CALIBRATION PREVIEW</span>
          <button className="back-link" type="button" onClick={onHome}>
            ← 처음으로 돌아가기
          </button>
        </div>

        <div className="calibration-stage" aria-hidden="true">
          <div className="calibration-stage__guide">
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <span className="calibration-target" />
          <p>FOLLOW THE DOT WITH YOUR EYES</p>
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
    <main className="store-screen placeholder-screen">
      <Wordmark />
      <p>다음 화면을 준비 중입니다.</p>
    </main>
  );
}

export default App;
