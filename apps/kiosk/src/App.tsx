import { useCallback, useEffect, useRef, useState } from "react";
import bagImage from "./assets/categories/category-bags.png";
import apparelImage from "./assets/categories/category-apparel.png";
import accessoryImage from "./assets/categories/category-accessories.png";
import screensaverImageOne from "./assets/categories/screensaver-01.jpg";
import screensaverCommunityImage from "./assets/screensaver/mcm-community.png";
import screensaverCraftImage from "./assets/screensaver/mcm-craft.png";
import screensaverGreenEditorialImage from "./assets/screensaver/mcm-green-editorial.jpg";
import screensaverGreenLoungeImage from "./assets/screensaver/mcm-green-lounge.jpg";
import screensaverHeritageCartImage from "./assets/screensaver/mcm-heritage-cart.jpg";
import screensaverLifestyleImage from "./assets/screensaver/mcm-lifestyle.png";
import screensaverLifestyleWideImage from "./assets/screensaver/mcm-lifestyle-wide.jpg";
import screensaverMilanStreetImage from "./assets/screensaver/mcm-milan-street.jpg";
import { AsyncFlowController } from "./app/async-flow-controller.ts";
import {
  CONSENT_IDLE_TIMEOUT_MS,
  CONSENT_VERSION,
  getConsentSecondsRemaining,
  runSessionStartWithTimeout,
  SessionStartTimeoutError,
} from "./app/consent-flow.ts";
import {
  INITIAL_KIOSK_SCREEN,
  transitionKioskScreen,
  type KioskEvent,
} from "./app/kiosk-machine.ts";
import { buildD1ReactionBatch } from "./app/reaction-batch.ts";
import type { FrameContext } from "./app/video-context.ts";
import type {
  ExpressionSample,
  GazeSample,
  KioskScreen,
  LookbookManifest,
  ProductCategory,
  RecommendationResult,
  SessionCreated,
} from "./app/kiosk-types.ts";
import {
  MOCK_LOOKBOOK_ID_BY_CATEGORY,
  MockApiClient,
} from "./clients/api/MockApiClient.ts";
import { CameraAccessError, FrameSource } from "./camera/FrameSource.ts";
import { FakeRemoteVisionClient } from "./clients/vision/FakeRemoteVisionClient.ts";
import {
  LookbookPlayer,
  type CameraDisplayState,
} from "./components/LookbookPlayer.tsx";
import "./App.css";

const apiClient = new MockApiClient({ sessionStartDelayMs: 450 });
const visionClient = new FakeRemoteVisionClient();
const frameSource = new FrameSource();
const temporaryLookbookVideoUrl = import.meta.env.VITE_LOOKBOOK_VIDEO_URL?.trim() ?? "";

type ConsentIssue =
  | "idle-timeout"
  | "session-timeout"
  | "session-error"
  | "camera-denied"
  | "camera-error";

const calibrationPattern = {
  pattern_id: "five-point-v1",
  points: [
    [0.5, 0.5],
    [0.1, 0.1],
    [0.9, 0.1],
    [0.1, 0.9],
    [0.9, 0.9],
  ] as [number, number][],
};

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

const screensaverStories = [
  {
    title: "MCM Heritage Since 1976",
    body: "Founded during Munich's golden age, MCM became a symbol of bold expression and the jet set life. Beloved by cultural icons and creative pioneers, the house continues to inspire through a progressive balance of innovation and craft.",
  },
  {
    title: "Beyond 50 Years of Excellence",
    body: "To mark its anniversary in 2026, MCM begins a yearlong celebration of craft and heritage. Moments shaped by the spirit of the times will connect its community, culminating in Munich where the story began, alongside a new logo created for the 50th anniversary.",
  },
  {
    title: "Crafted With Purpose",
    body: "From the beginning, MCM has followed the Bauhaus belief that form follows function. Rooted in German engineering, each piece balances purposeful detail, refined style and exceptional materials, creating hands free designs made for life in motion.",
  },
];

const screensaverSlides = [
  {
    className: "screensaver__slide--green-editorial",
    image: screensaverGreenEditorialImage,
    storyIndex: 0,
  },
  {
    className: "screensaver__slide--heritage-cart",
    image: screensaverHeritageCartImage,
    storyIndex: 0,
  },
  {
    className: "screensaver__slide--craft",
    image: screensaverCraftImage,
    storyIndex: 0,
  },
  {
    className: "screensaver__slide--community",
    image: screensaverCommunityImage,
    storyIndex: 1,
  },
  {
    className: "screensaver__slide--milan-street",
    image: screensaverMilanStreetImage,
    storyIndex: 1,
  },
  {
    className: "screensaver__slide--lifestyle-wide",
    image: screensaverLifestyleWideImage,
    storyIndex: 1,
  },
  {
    className: "screensaver__slide--green-lounge",
    image: screensaverGreenLoungeImage,
    storyIndex: 2,
  },
  {
    className: "screensaver__slide--lifestyle",
    image: screensaverLifestyleImage,
    storyIndex: 2,
  },
];

function getLookbookPoster(category: ProductCategory | null): string {
  if (category === "가방") return bagImage;
  if (category === "의류") return apparelImage;
  if (category === "액세서리") return accessoryImage;
  return screensaverImageOne;
}

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
  const activeStory = screensaverStories[screensaverSlides[activeSlide].storyIndex];

  useEffect(() => {
    const slideTimer = window.setInterval(() => {
      setActiveSlide((currentSlide) => (currentSlide + 1) % screensaverSlides.length);
    }, 5000);

    return () => window.clearInterval(slideTimer);
  }, []);

  return (
    <main className="store-screen screensaver screen-enter" aria-labelledby="screensaver-title">
      <button
        className="screensaver__hit-area"
        type="button"
        onClick={onStart}
        aria-label="touch to start"
      />

      <div className="screensaver__media" aria-hidden="true">
        {screensaverSlides.map((slide, index) => (
          <div
            className={`screensaver__slide ${slide.className}${
              index === activeSlide ? " is-active" : ""
            }`}
            key={slide.image}
          >
            <img src={slide.image} alt="" />
          </div>
        ))}
      </div>

      <div className="screensaver__brand">
        <Wordmark light />
      </div>

      <section className="screensaver__copy">
        <p className="screensaver__signature" lang="en" aria-hidden="true">
          a taste waiting to be discovered
        </p>
        <h1 id="screensaver-title">
          고객님의 취향을
          <br />
          발견해드립니다
        </h1>
        <span className="screensaver__cta" lang="en">
          touch to start
        </span>
      </section>

      <aside className="screensaver__editorial" key={activeStory.title}>
        <h2>{activeStory.title}</h2>
        <p>{activeStory.body}</p>
      </aside>
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
  onCancel,
  onContinue,
  onHome,
  onRetry,
  onTimeout,
  isStarting,
  issue,
}: {
  category: ProductCategory | null;
  onBack: () => void;
  onCancel: () => void;
  onContinue: () => void;
  onHome: () => void;
  onRetry: () => void;
  onTimeout: () => void;
  isStarting: boolean;
  issue: ConsentIssue | null;
}) {
  const [secondsRemaining, setSecondsRemaining] = useState(
    getConsentSecondsRemaining(CONSENT_IDLE_TIMEOUT_MS, 0),
  );

  useEffect(() => {
    if (isStarting || issue) return;

    const deadlineMs = Date.now() + CONSENT_IDLE_TIMEOUT_MS;
    let didTimeout = false;
    const resetTimer = window.setTimeout(() => {
      setSecondsRemaining(getConsentSecondsRemaining(deadlineMs, Date.now()));
    }, 0);

    const countdownTimer = window.setInterval(() => {
      const nextSeconds = getConsentSecondsRemaining(deadlineMs, Date.now());
      setSecondsRemaining(nextSeconds);

      if (nextSeconds === 0 && !didTimeout) {
        didTimeout = true;
        window.clearInterval(countdownTimer);
        onTimeout();
      }
    }, 250);

    return () => {
      window.clearTimeout(resetTimer);
      window.clearInterval(countdownTimer);
    };
  }, [isStarting, issue, onTimeout]);

  const issueContent = issue
    ? {
        "idle-timeout": {
          eyebrow: "SESSION TIMEOUT",
          title: "입력 시간이 지났어요",
          description:
            "동의가 확인되지 않아 카메라와 Mock 세션을 시작하지 않았습니다.",
          retryLabel: "내용 다시 확인하기",
        },
        "session-timeout": {
          eyebrow: "MOCK API TIMEOUT",
          title: "세션 준비가 지연되고 있어요",
          description:
            "열렸던 카메라는 종료했습니다. 잠시 후 Mock 세션 연결을 다시 시도해주세요.",
          retryLabel: "다시 시도",
        },
        "session-error": {
          eyebrow: "MOCK API ERROR",
          title: "세션을 준비하지 못했어요",
          description:
            "열렸던 카메라는 종료했습니다. Mock API 상태를 확인한 뒤 다시 시도해주세요.",
          retryLabel: "다시 시도",
        },
        "camera-denied": {
          eyebrow: "CAMERA PERMISSION",
          title: "카메라 권한이 필요해요",
          description:
            "브라우저에서 카메라 사용을 허용한 뒤 다시 시도해주세요. 권한을 허용하기 전에는 분석 세션을 시작하지 않습니다.",
          retryLabel: "권한 다시 확인",
        },
        "camera-error": {
          eyebrow: "CAMERA ERROR",
          title: "카메라를 시작하지 못했어요",
          description:
            "카메라 연결 상태를 확인한 뒤 다시 시도해주세요. 열렸던 camera track은 모두 종료했습니다.",
          retryLabel: "카메라 다시 연결",
        },
      }[issue]
    : null;

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
            시선과 표정 관련 신호를 분석해 관심 있는 스타일을 찾습니다. 아래 내용에
            동의하기 전에는 카메라와 세션이 시작되지 않습니다.
          </p>

          <dl className="privacy-list">
            <div>
              <dt>01</dt>
              <dd>
                <strong>카메라 영상만 사용합니다</strong>
                <span>동의 후 룩북 재생 중에만 사용하며 음성은 수집·전송하지 않습니다.</span>
              </dd>
            </div>
            <div>
              <dt>02</dt>
              <dd>
                <strong>원격 분석 서버로 일시 전송합니다</strong>
                <span>
                  프레임은 암호화된 연결로 별도 Vision 서버에 전송되어 시선·표정 분석에만
                  사용됩니다.
                </span>
              </dd>
            </div>
            <div>
              <dt>03</dt>
              <dd>
                <strong>원본 프레임은 저장하지 않습니다</strong>
                <span>
                  서버 메모리에서 처리한 뒤 즉시 해제하며 파일·DB·로그·cache에 남기지
                  않습니다.
                </span>
              </dd>
            </div>
            <div>
              <dt>04</dt>
              <dd>
                <strong>개별 파생 신호는 저장하지 않습니다</strong>
                <span>
                  시선·표정 관련 신호는 현재 세션에서 관심도를 집계하는 데만 사용하고 추천
                  생성 후 폐기합니다. 추천 결과와 익명 세션 상태는 현재 세션에만 유지합니다.
                </span>
              </dd>
            </div>
          </dl>

          <div className="consent-meta">
            <span>D03 LOCAL CAMERA · 원격 전송 없이 fake 경계로 확인합니다.</span>
            <span role="timer" aria-label={`자동 종료까지 ${secondsRemaining}초`}>
              AUTO CLOSE · {String(secondsRemaining).padStart(2, "0")}S
            </span>
          </div>

          <button
            className="back-link consent-back"
            type="button"
            onClick={onBack}
            disabled={isStarting || issue !== null}
          >
            ← 카테고리 다시 선택
          </button>

          <div className="consent-actions">
            <button
              className="store-button store-button--outline"
              type="button"
              onClick={onCancel}
              disabled={isStarting || issue !== null}
            >
              동의하지 않고 종료
            </button>
            <button
              className="store-button store-button--solid"
              type="button"
              onClick={onContinue}
              disabled={isStarting || issue !== null}
              aria-busy={isStarting}
            >
              {isStarting ? "카메라·Mock 세션 준비 중..." : "동의하고 계속"}
              {!isStarting && <ArrowIcon />}
            </button>
          </div>

          {issueContent && (
            <section
              className="consent-feedback"
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="consent-feedback-title"
            >
              <p className="section-label">{issueContent.eyebrow}</p>
              <h2 id="consent-feedback-title">{issueContent.title}</h2>
              <p>{issueContent.description}</p>
              <div className="consent-feedback__actions">
                <button
                  className="store-button store-button--outline"
                  type="button"
                  onClick={onCancel}
                >
                  처음 화면으로
                </button>
                <button
                  className="store-button store-button--solid"
                  type="button"
                  onClick={onRetry}
                >
                  {issueContent.retryLabel}
                </button>
              </div>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}

function Calibration({
  onHome,
  onComplete,
}: {
  onHome: () => void;
  onComplete: () => Promise<void>;
}) {
  useEffect(() => {
    const calibrationTimer = window.setTimeout(() => {
      void onComplete();
    }, 1800);

    return () => window.clearTimeout(calibrationTimer);
  }, [onComplete]);

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

function TimedPlaceholder({
  message,
  onComplete,
  onHome,
}: {
  message: string;
  onComplete: () => Promise<void>;
  onHome: () => void;
}) {
  useEffect(() => {
    const stepTimer = window.setTimeout(() => {
      void onComplete();
    }, 1800);

    return () => window.clearTimeout(stepTimer);
  }, [onComplete]);

  return (
    <main className="store-screen placeholder-screen">
      <button className="wordmark-button" type="button" onClick={onHome}>
        <Wordmark />
        <span className="sr-only">처음 화면으로 이동</span>
      </button>
      <p>{message}</p>
    </main>
  );
}

function ReportPlaceholder({
  recommendation,
  onHome,
}: {
  recommendation: RecommendationResult;
  onHome: () => void;
}) {
  const productIds = recommendation.items.map((item) => item.product_id).join(" · ");

  return (
    <main className="store-screen placeholder-screen">
      <Wordmark />
      <p>Mock 추천 결과: {productIds || "추천 결과 없음"}</p>
      <button className="back-link" type="button" onClick={onHome}>
        ← 처음으로 돌아가기
      </button>
    </main>
  );
}

function ErrorPlaceholder({ message, onHome }: { message: string; onHome: () => void }) {
  return (
    <main className="store-screen placeholder-screen" role="alert">
      <Wordmark />
      <p>{message}</p>
      <button className="back-link" type="button" onClick={onHome}>
        ← 처음으로 돌아가기
      </button>
    </main>
  );
}

function App() {
  const [screen, setScreen] = useState<KioskScreen>(INITIAL_KIOSK_SCREEN);
  const [selectedCategory, setSelectedCategory] = useState<ProductCategory | null>(null);
  const [session, setSession] = useState<SessionCreated | null>(null);
  const [manifest, setManifest] = useState<LookbookManifest | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationResult | null>(null);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [consentIssue, setConsentIssue] = useState<ConsentIssue | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [cameraState, setCameraState] = useState<CameraDisplayState>("idle");
  const [flowController] = useState(() => new AsyncFlowController());
  const latestGazeSample = useRef<GazeSample | null>(null);
  const latestExpressionSample = useRef<ExpressionSample | null>(null);
  const sessionStartAbortController = useRef<AbortController | null>(null);

  const abortSessionStart = useCallback(() => {
    sessionStartAbortController.current?.abort();
    sessionStartAbortController.current = null;
  }, []);

  const send = useCallback((event: KioskEvent) => {
    setScreen((currentScreen) => transitionKioskScreen(currentScreen, event));
  }, []);

  useEffect(() => {
    const removeGazeListener = visionClient.onGazeSample((sample) => {
      latestGazeSample.current = sample;
    });
    const removeExpressionListener = visionClient.onExpressionSample((sample) => {
      latestExpressionSample.current = sample;
    });

    return () => {
      removeGazeListener();
      removeExpressionListener();
      flowController.invalidateCurrentFlow();
      abortSessionStart();
      frameSource.stop();
      void flowController.runSerialized(() => visionClient.stopSession());
    };
  }, [abortSessionStart, flowController]);

  const selectCategory = (category: ProductCategory) => {
    setSelectedCategory(category);
    setConsentIssue(null);
    send("SELECT_CATEGORY");
  };

  const restart = useCallback(async () => {
    const generation = flowController.invalidateCurrentFlow();
    abortSessionStart();
    frameSource.stop();
    if (session) apiClient.discardSession(session.session_id);
    latestGazeSample.current = null;
    latestExpressionSample.current = null;
    setSelectedCategory(null);
    setSession(null);
    setManifest(null);
    setRecommendation(null);
    setFlowError(null);
    setConsentIssue(null);
    setIsStarting(false);
    setCameraState("idle");
    send("RESTART");

    try {
      await flowController.runSerialized(() => visionClient.stopSession());
    } catch {
      if (flowController.isCurrent(generation)) {
        setFlowError("이전 Vision 세션을 종료하지 못했습니다.");
      }
    }
  }, [abortSessionStart, flowController, send, session]);

  const cancelConsent = useCallback(async () => {
    const generation = flowController.invalidateCurrentFlow();
    abortSessionStart();
    frameSource.stop();
    latestGazeSample.current = null;
    latestExpressionSample.current = null;
    setSelectedCategory(null);
    setSession(null);
    setManifest(null);
    setRecommendation(null);
    setFlowError(null);
    setConsentIssue(null);
    setIsStarting(false);
    setCameraState("idle");
    send("CANCEL");

    try {
      await flowController.runSerialized(() => visionClient.stopSession());
    } catch {
      if (flowController.isCurrent(generation)) {
        setFlowError("이전 Vision 세션을 종료하지 못했습니다.");
      }
    }
  }, [abortSessionStart, flowController, send]);

  const handleConsentTimeout = useCallback(() => {
    const generation = flowController.invalidateCurrentFlow();
    abortSessionStart();
    frameSource.stop();
    latestGazeSample.current = null;
    latestExpressionSample.current = null;
    setIsStarting(false);
    setCameraState("idle");
    setConsentIssue("idle-timeout");

    void flowController.runSerialized(() => visionClient.stopSession()).catch(() => {
      if (flowController.isCurrent(generation)) {
        setFlowError("시간 초과 후 Vision 세션을 정리하지 못했습니다.");
      }
    });
  }, [abortSessionStart, flowController]);

  const beginSession = async () => {
    if (!selectedCategory || isStarting || sessionStartAbortController.current) return;

    const generation = flowController.invalidateCurrentFlow();
    const abortController = new AbortController();
    sessionStartAbortController.current = abortController;
    setIsStarting(true);
    setFlowError(null);
    setConsentIssue(null);
    setCameraState("requesting");

    try {
      await frameSource.open();
      if (!flowController.isCurrent(generation)) {
        frameSource.stop();
        return;
      }
      setCameraState("ready");

      const lookbookId = MOCK_LOOKBOOK_ID_BY_CATEGORY[selectedCategory];
      const { createdSession, lookbookManifest } = await runSessionStartWithTimeout(
        async (signal) => {
          const lookbookManifest = await apiClient.getLookbookManifest(lookbookId, {
            signal,
          });
          signal.throwIfAborted();

          const createdSession = await apiClient.createSession(
            {
              kiosk_id: "mcm-kiosk-d1",
              lookbook_id: lookbookId,
              consent_version: CONSENT_VERSION,
            },
            { signal },
          );
          signal.throwIfAborted();

          await flowController.runSerialized(() =>
            visionClient.startSession(
              {
                session_id: createdSession.session_id,
                video_id: lookbookManifest.video_id,
              },
              { signal },
            ),
          );
          signal.throwIfAborted();

          return { createdSession, lookbookManifest };
        },
        { signal: abortController.signal },
      );
      if (!flowController.isCurrent(generation)) return;

      setSession(createdSession);
      setManifest(lookbookManifest);
      send("AGREE");
    } catch (error: unknown) {
      frameSource.stop();
      if (flowController.isCurrent(generation)) {
        const isCameraError = error instanceof CameraAccessError;
        setCameraState(
          isCameraError
            ? error.code === "permission_denied"
              ? "denied"
              : "error"
            : "idle",
        );
        setConsentIssue(
          isCameraError
            ? error.code === "permission_denied"
              ? "camera-denied"
              : "camera-error"
            : error instanceof SessionStartTimeoutError
              ? "session-timeout"
              : "session-error",
        );

        void flowController.runSerialized(() => visionClient.stopSession()).catch(() => {
          if (flowController.isCurrent(generation)) {
            setFlowError("세션 시작 실패 후 Vision 세션을 정리하지 못했습니다.");
          }
        });
      }
    } finally {
      if (sessionStartAbortController.current === abortController) {
        sessionStartAbortController.current = null;
      }
      if (flowController.isCurrent(generation)) setIsStarting(false);
    }
  };

  const completeCalibration = useCallback(async () => {
    const generation = flowController.captureGeneration();

    try {
      const result = await flowController.runSerialized(() =>
        visionClient.startCalibration(calibrationPattern),
      );
      if (!flowController.isCurrent(generation)) return;

      if (!result.valid) throw new Error(result.reason ?? "calibration_failed");
      await flowController.runSerialized(() => visionClient.startInference());

      if (flowController.isCurrent(generation)) send("CALIBRATION_SUCCESS");
    } catch {
      frameSource.stop();
      if (flowController.isCurrent(generation)) {
        setCameraState("error");
        setFlowError("Mock 시선 보정을 완료하지 못했습니다.");
      }
    }
  }, [flowController, send]);

  const completeLookbook = useCallback(async () => {
    const generation = flowController.captureGeneration();
    frameSource.stop();
    setCameraState("idle");

    if (!session || !manifest) {
      setFlowError("진행 중인 Mock 세션 정보를 찾지 못했습니다.");
      return;
    }

    try {
      await flowController.runSerialized(() => visionClient.stopSession());
      if (!flowController.isCurrent(generation)) return;

      const gazeSample = latestGazeSample.current;
      const expressionSample = latestExpressionSample.current;
      const batch = buildD1ReactionBatch({
        batchId: `batch-${session.session_id}-0001`,
        batchSequence: 0,
        sessionId: session.session_id,
        manifest,
        gazeSample,
        expressionSample,
      });

      if (batch) {
        if (!flowController.isCurrent(generation)) return;
        await apiClient.appendReactionBatch(session.session_id, batch);
      }

      if (!flowController.isCurrent(generation)) return;
      await apiClient.completeSessionAnalysis(session.session_id);
      if (flowController.isCurrent(generation)) send("LOOKBOOK_FINISHED");
    } catch {
      if (flowController.isCurrent(generation)) {
        setFlowError("Mock 룩북 분석을 완료하지 못했습니다.");
      }
    } finally {
      if (flowController.isCurrent(generation)) {
        latestGazeSample.current = null;
        latestExpressionSample.current = null;
      }
    }
  }, [flowController, manifest, send, session]);

  const captureCameraFrame = useCallback(
    async (context: FrameContext) => {
      const generation = flowController.captureGeneration();

      try {
        await frameSource.capture(context, async (frame, frameContext, signal) => {
          await visionClient.sendFrame(frame, frameContext, { signal });
        });
      } catch (error: unknown) {
        if (
          !flowController.isCurrent(generation) ||
          (error instanceof CameraAccessError && error.code === "cancelled")
        ) {
          return;
        }

        frameSource.stop();
        setCameraState(
          error instanceof CameraAccessError && error.code === "permission_denied"
            ? "denied"
            : "error",
        );
      }
    },
    [flowController],
  );

  const retryCamera = useCallback(async () => {
    const generation = flowController.captureGeneration();
    frameSource.stop();
    setCameraState("requesting");

    try {
      await frameSource.open();
      if (flowController.isCurrent(generation)) setCameraState("ready");
      else frameSource.stop();
    } catch (error: unknown) {
      if (!flowController.isCurrent(generation)) return;
      setCameraState(
        error instanceof CameraAccessError && error.code === "permission_denied"
          ? "denied"
          : "error",
      );
    }
  }, [flowController]);

  const handlePlaybackUnavailable = useCallback(() => {
    frameSource.stop();
    setCameraState("idle");
  }, []);

  const loadRecommendation = useCallback(async () => {
    const generation = flowController.captureGeneration();

    if (!session) {
      setFlowError("추천에 필요한 Mock 세션 정보를 찾지 못했습니다.");
      return;
    }

    try {
      if (!flowController.isCurrent(generation)) return;
      const result = await apiClient.getSessionRecommendation(session.session_id);
      if (!flowController.isCurrent(generation)) return;

      if (result.status !== "completed") {
        throw new Error(result.reason ?? "recommendation_not_ready");
      }

      if (flowController.isCurrent(generation)) {
        setRecommendation(result);
        send("RECOMMENDATION_READY");
      }
    } catch {
      if (flowController.isCurrent(generation)) {
        setFlowError("Mock 추천 결과를 불러오지 못했습니다.");
      }
    }
  }, [flowController, send, session]);

  if (flowError) {
    return <ErrorPlaceholder message={flowError} onHome={restart} />;
  }

  if (screen === "screensaver") {
    return <Screensaver onStart={() => send("START")} />;
  }

  if (screen === "menu") {
    return <CategoryMenu onSelect={selectCategory} onHome={restart} />;
  }

  if (screen === "consent") {
    return (
      <CameraConsent
        category={selectedCategory}
        onBack={() => {
          frameSource.stop();
          setCameraState("idle");
          setSelectedCategory(null);
          setConsentIssue(null);
          send("BACK");
        }}
        onCancel={() => void cancelConsent()}
        onContinue={() => void beginSession()}
        onHome={restart}
        onRetry={() => {
          const shouldRestartSession = consentIssue !== "idle-timeout";
          setConsentIssue(null);
          if (shouldRestartSession) void beginSession();
        }}
        onTimeout={handleConsentTimeout}
        isStarting={isStarting}
        issue={consentIssue}
      />
    );
  }

  if (screen === "calibration") {
    return <Calibration onHome={restart} onComplete={completeCalibration} />;
  }

  if (screen === "lookbook") {
    if (!session || !manifest) {
      return (
        <ErrorPlaceholder
          message="룩북 재생에 필요한 Mock 세션 정보를 찾지 못했습니다."
          onHome={restart}
        />
      );
    }

    return (
      <LookbookPlayer
        key={manifest.video_id}
        cameraState={cameraState}
        categoryLabel={selectedCategory ?? "전체 컬렉션"}
        chrome={<StoreChrome onHome={restart} step="03" overlay />}
        posterUrl={getLookbookPoster(selectedCategory)}
        sessionId={session.session_id}
        videoId={manifest.video_id}
        videoUrl={temporaryLookbookVideoUrl}
        onCameraRetry={retryCamera}
        onComplete={completeLookbook}
        onFrameCapture={captureCameraFrame}
        onHome={restart}
        onPlaybackUnavailable={handlePlaybackUnavailable}
      />
    );
  }

  if (screen === "finalizing") {
    return (
      <TimedPlaceholder
        message="Mock 추천 결과를 준비하고 있습니다."
        onComplete={loadRecommendation}
        onHome={restart}
      />
    );
  }

  if (screen === "report" && recommendation) {
    return <ReportPlaceholder recommendation={recommendation} onHome={restart} />;
  }

  return (
    <main className="store-screen placeholder-screen">
      <Wordmark />
      <p>다음 화면을 준비 중입니다.</p>
    </main>
  );
}

export default App;
