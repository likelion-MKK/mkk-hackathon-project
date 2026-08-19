import { useCallback, useEffect, useRef, useState } from "react";
import bagImage from "./assets/categories/category-bags.png";
import apparelImage from "./assets/categories/category-apparel.png";
import accessoryImage from "./assets/categories/category-accessories.png";
import menuApparelImage from "./assets/categories/category-apparel-menu.png";
import menuAccessoryImage from "./assets/categories/category-accessories-menu.png";
import menuCollectionImage from "./assets/categories/category-collection-menu.png";
import screensaverImageOne from "./assets/categories/screensaver-01.jpg";
import screensaverCommunityImage from "./assets/screensaver/mcm-community.png";
import screensaverCraftImage from "./assets/screensaver/mcm-craft.png";
import screensaverGreenEditorialImage from "./assets/screensaver/mcm-green-editorial.jpg";
import screensaverGreenLoungeImage from "./assets/screensaver/mcm-green-lounge.jpg";
import screensaverHeritageCartImage from "./assets/screensaver/mcm-heritage-cart.jpg";
import screensaverLifestyleImage from "./assets/screensaver/mcm-lifestyle.png";
import screensaverLifestyleWideImage from "./assets/screensaver/mcm-lifestyle-wide.jpg";
import screensaverMilanStreetImage from "./assets/screensaver/mcm-milan-street.jpg";
import {
  ACTUAL_LOOKBOOK_ID,
  resolveActualLookbookConfig,
} from "./app/actual-lookbook-config.ts";
import { AsyncFlowController } from "./app/async-flow-controller.ts";
import {
  discardCentralSessionBestEffort,
  submitCentralRecommendation,
} from "./app/central-recommendation-flow.ts";
import {
  CONSENT_IDLE_TIMEOUT_MS,
  CONSENT_VERSION,
  getConsentSecondsRemaining,
  runSessionStartWithTimeout,
  SessionStartTimeoutError,
} from "./app/consent-flow.ts";
import {
  CALIBRATION_CAPTURE_INTERVAL_MS,
  CALIBRATION_PATTERN,
  CALIBRATION_TARGET_TRANSITION_MS,
  FULLSCREEN_TRAINING_POINTS,
  calibrationFailureMessage,
  calibrationDwellMs,
} from "./app/calibration-plan.ts";
import {
  INITIAL_KIOSK_SCREEN,
  transitionKioskScreen,
  type KioskEvent,
} from "./app/kiosk-machine.ts";
import { buildManagerProductRequestV2 } from "./app/manager-product-request-v2.ts";
import { buildObservationBatchesV2 } from "./app/observation-batch-v2.ts";
import { resolveProductDisplayPolicy } from "./app/product-display-policy.ts";
import { buildD1ReactionBatches } from "./app/reaction-batch.ts";
import {
  pollRecommendation,
  RecommendationPollingError,
} from "./app/recommendation-polling.ts";
import {
  presentCentralRecommendation,
  presentMockRecommendation,
  type RecommendationPresentation,
} from "./app/recommendation-presentation.ts";
import {
  calculateContainedVideoLayout,
  createFrameContext,
  type FrameContext,
  type VideoLayout,
} from "./app/video-context.ts";
import type {
  GazeSample,
  GazeUnavailableSample,
  KioskScreen,
  LookbookManifest,
  Product,
  ProductCategory,
  ProductRecommendationItemV2,
  RecommendationAcceptedV2,
  RecommendationDecisionV2,
  RecommendationResult,
  SessionCreated,
} from "./app/kiosk-types.ts";
import {
  MOCK_LOOKBOOK_ID_BY_CATEGORY,
  MockApiClient,
} from "./clients/api/MockApiClient.ts";
import type { ApiClient } from "./clients/api/ApiClient.ts";
import { HttpApiClient } from "./clients/api/HttpApiClient.ts";
import { CameraAccessError, FrameSource } from "./camera/FrameSource.ts";
import { browserFrameEncoder } from "./clients/vision/BrowserFrameEncoder.ts";
import { FakeRemoteVisionClient } from "./clients/vision/FakeRemoteVisionClient.ts";
import {
  createFetchVisionStreamTokenProvider,
  LocalVisionStreamClient,
} from "./clients/vision/LocalVisionStreamClient.ts";
import {
  LookbookPlayer,
  type CameraDisplayState,
} from "./components/LookbookPlayer.tsx";
import "./App.css";

const useMockApi = import.meta.env.VITE_USE_MOCK_API?.trim().toLowerCase() === "true";
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
const actualLookbookConfig = useMockApi
  ? null
  : resolveActualLookbookConfig(
      import.meta.env.VITE_LOOKBOOK_ID,
      import.meta.env.VITE_LOOKBOOK_VIDEO_URL,
    );
const configuredLookbookId = actualLookbookConfig?.lookbookId ?? ACTUAL_LOOKBOOK_ID;
const mockApiClient = new MockApiClient({ sessionStartDelayMs: 450 });
const httpApiClient = new HttpApiClient(apiBaseUrl);
const apiClient: ApiClient = useMockApi ? mockApiClient : httpApiClient;
const frameSource = new FrameSource();
const configuredLookbookVideoUrl = actualLookbookConfig?.videoUrl ?? "";
const configuredVisionMode = import.meta.env.VITE_VISION_MODE?.trim() || "replay";
if (configuredVisionMode !== "replay" && configuredVisionMode !== "live") {
  throw new Error("VITE_VISION_MODE must be replay or live.");
}
const visionTokenEndpoint =
  import.meta.env.VITE_VISION_TOKEN_URL?.trim() ||
  "/api/v1/sessions/{session_id}/vision-stream-token";
const visionTokenMode =
  import.meta.env.VITE_VISION_TOKEN_MODE?.trim().toLowerCase() === "local"
    ? "local"
    : "backend";
const visionClient =
  configuredVisionMode === "live"
    ? new LocalVisionStreamClient({
        tokenProvider: createFetchVisionStreamTokenProvider({
          endpoint: visionTokenEndpoint,
          mode: visionTokenMode,
        }),
        websocketUrl: import.meta.env.VITE_VISION_GATEWAY_WS_URL?.trim() || undefined,
        frameEncoder: browserFrameEncoder,
      })
    : new FakeRemoteVisionClient();
const enableAoiDebugOverlay =
  import.meta.env.DEV || import.meta.env.VITE_KIOSK_DEBUG_AOI === "true";
const MAX_CAPTURED_FRAME_LAYOUTS = 2_048;

function rememberCapturedFrameLayout(
  layoutsByFrameId: Map<string, VideoLayout>,
  context: FrameContext,
): void {
  layoutsByFrameId.set(context.frame_id, context.layout);

  if (layoutsByFrameId.size > MAX_CAPTURED_FRAME_LAYOUTS) {
    const oldestFrameId = layoutsByFrameId.keys().next().value;
    if (oldestFrameId) layoutsByFrameId.delete(oldestFrameId);
  }
}

type ConsentIssue =
  | "idle-timeout"
  | "session-timeout"
  | "session-error"
  | "camera-denied"
  | "camera-error";

type CategoryOption = {
  name: ProductCategory;
  label: string;
  englishName: string;
};

const mockProductCategories: CategoryOption[] = [
  {
    name: "가방",
    label: "가방",
    englishName: "BAGS",
  },
  {
    name: "의류",
    label: "의류",
    englishName: "READY-TO-WEAR",
  },
  {
    name: "액세서리",
    label: "악세서리",
    englishName: "ACCESSORIES",
  },
  {
    name: "전체 컬렉션",
    label: "전체컬렉션",
    englishName: "VIEW ALL",
  },
];

const productCategories: CategoryOption[] = mockProductCategories;

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
        <p className="screensaver__eyebrow">고객님의 취향을 발견해드립니다</p>
        <h1 id="screensaver-title" lang="en">
          A taste waiting
          <br />
          to be discovered
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

function CategoryMedia({ category }: { category: ProductCategory }) {
  if (category === "가방") {
    return <img className="category-card__image category-card__image--bag" src={bagImage} alt="" />;
  }

  if (category === "의류") {
    return (
      <img
        className="category-card__image category-card__image--apparel"
        src={menuApparelImage}
        alt=""
      />
    );
  }

  if (category === "액세서리") {
    return (
      <img
        className="category-card__image category-card__image--accessory"
        src={menuAccessoryImage}
        alt=""
      />
    );
  }

  return (
    <img
      className="category-card__image category-card__image--collection"
      src={menuCollectionImage}
      alt=""
    />
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
      <header className="gallery-header">
        <button className="wordmark-button gallery-home" type="button" onClick={onHome}>
          <Wordmark light />
          <span className="sr-only">처음 화면으로 이동</span>
        </button>
      </header>

      <section className="gallery-heading" aria-labelledby="menu-title">
        <p className="gallery-heading__eyebrow" lang="en">
          choose a category
        </p>
        <h1 id="menu-title">원하는 카테고리를 선택하세요</h1>
      </section>

      <section className="category-gallery" aria-label="상품 카테고리">
        {productCategories.map((category) => (
          <button
            className="category-card"
            key={category.name}
            type="button"
            onClick={() => onSelect(category.name)}
          >
            <span className="category-card__media">
              <CategoryMedia category={category.name} />
            </span>
            <span className="category-card__details">
              <strong>{category.label}</strong>
              <small lang="en">{category.englishName}</small>
            </span>
          </button>
        ))}
      </section>

      <footer className="gallery-footer">
        <aside className="gallery-editorial" aria-labelledby="gallery-editorial-title">
          <h2 id="gallery-editorial-title" lang="en">
            Designed for every journey
          </h2>
          <p lang="en">
            Mobility has always been at the heart of MCM. Since Michael Cromer introduced the
            house&apos;s first travel pieces in 1976, MCM has continued to design for today&apos;s
            nomads, who see the world as home.
          </p>
        </aside>
      </footer>
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
            "동의가 확인되지 않아 카메라와 분석 세션을 시작하지 않았습니다.",
          retryLabel: "내용 다시 확인하기",
        },
        "session-timeout": {
          eyebrow: useMockApi ? "MOCK API TIMEOUT" : "API TIMEOUT",
          title: "세션 준비가 지연되고 있어요",
          description:
            `열렸던 카메라는 종료했습니다. 잠시 후 ${useMockApi ? "Mock" : "Backend"} 세션 연결을 다시 시도해주세요.`,
          retryLabel: "다시 시도",
        },
        "session-error": {
          eyebrow: useMockApi ? "MOCK API ERROR" : "API ERROR",
          title: "세션을 준비하지 못했어요",
          description:
            `열렸던 카메라는 종료했습니다. ${useMockApi ? "Mock API" : "Backend"} 상태를 확인한 뒤 다시 시도해주세요.`,
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
            시선의 관찰 가능한 신호만 분석해 관심 있는 스타일을 찾습니다. 표정 분석은
            사용하지 않습니다. 아래 내용에 동의하기 전에는 카메라와 세션이 시작되지
            않습니다.
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
                <strong>현재는 local gaze-only 분석 경계를 사용합니다</strong>
                <span>
                  원본 프레임은 중앙 추천 서버로 보내지 않으며 정형화된 시선 파생 JSON만
                  Backend에 전달합니다. 표정 필드는 null과 not_observed 사유를 보존합니다.
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
                  시선 관련 신호는 현재 세션에서 관심도를 집계하는 데만 사용하고 추천 생성
                  후 폐기합니다. 최종 추천은 최소 운영 metadata만 Backend 정책에 따라 처리합니다.
                </span>
              </dd>
            </div>
          </dl>

          <div className="consent-meta">
            <span>
              CENTRAL V2 · {configuredVisionMode === "live" ? "LOCAL LIVE GAZE-ONLY" : "REPLAY VISION"}
            </span>
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
              {isStarting ? "카메라·분석 세션 준비 중..." : "동의하고 계속"}
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
  onBegin,
  onComplete,
  onFrameCapture,
}: {
  onHome: () => void;
  onBegin: () => Promise<unknown>;
  onComplete: () => Promise<void>;
  onFrameCapture: () => Promise<void>;
}) {
  useEffect(() => {
    let active = true;
    const frameTimer = window.setInterval(() => {
      void onFrameCapture().catch(() => undefined);
    }, CALIBRATION_CAPTURE_INTERVAL_MS);

    void (async () => {
      try {
        await onBegin();
        if (active) await onComplete();
      } catch {
        // Complete the same guarded flow so a failed stream/calibration
        // request is surfaced by the parent instead of becoming an
        // unhandled promise rejection.
        if (active) await onComplete();
      } finally {
        window.clearInterval(frameTimer);
      }
    })();

    return () => {
      active = false;
      window.clearInterval(frameTimer);
    };
  }, [onBegin, onComplete, onFrameCapture]);

  const [targetIndex, setTargetIndex] = useState(0);
  useEffect(() => {
    let active = true;
    let currentIndex = 0;
    let targetTimer: number | undefined;
    const scheduleNextTarget = () => {
      const duration = calibrationDwellMs(currentIndex);
      targetTimer = window.setTimeout(() => {
        if (!active) return;
        currentIndex = (currentIndex + 1) % CALIBRATION_PATTERN.points.length;
        setTargetIndex(currentIndex);
        scheduleNextTarget();
      }, duration);
    };
    scheduleNextTarget();
    return () => {
      active = false;
      if (targetTimer !== undefined) window.clearTimeout(targetTimer);
    };
  }, []);
  const [targetX, targetY] = CALIBRATION_PATTERN.points[targetIndex] ?? [0.5, 0.5];
  const isTrainingTarget = targetIndex < FULLSCREEN_TRAINING_POINTS.length;
  const phaseIndex = isTrainingTarget ? targetIndex + 1 : targetIndex - FULLSCREEN_TRAINING_POINTS.length + 1;
  const phaseCount = isTrainingTarget
    ? FULLSCREEN_TRAINING_POINTS.length
    : CALIBRATION_PATTERN.points.length - FULLSCREEN_TRAINING_POINTS.length;

  return (
    <main className="store-screen calibration-screen screen-enter">
      <section className="calibration-page" aria-labelledby="calibration-title">
        <div className="calibration-page__copy">
          <p className="section-label">EYE CALIBRATION</p>
          <h1 id="calibration-title">
            화면 전체를 쓰는<br />
            정밀 시선 보정
          </h1>
          <p>
            고개는 편안히 두고 점만 눈으로 따라가세요. 점은 부드럽게 이동하며,
            한 번에 약 64초가 걸리며, 점이 멈춘 동안 계속 바라봐 주세요.
          </p>
          <p className="calibration-page__progress" aria-live="polite">
            {isTrainingTarget ? "보정" : "확인"} {phaseIndex}/{phaseCount}
          </p>
          <button className="back-link" type="button" onClick={onHome}>
            ← 처음으로 돌아가기
          </button>
        </div>

        <div className="calibration-stage" aria-hidden="true">
          <span
            className="calibration-target"
            style={{
              left: `${targetX * 100}%`,
              top: `${targetY * 100}%`,
              transitionDuration: `${CALIBRATION_TARGET_TRANSITION_MS}ms`,
            }}
          />
        </div>
      </section>
    </main>
  );
}

type AnalysisStatus =
  | "idle"
  | "preparing"
  | "requesting"
  | "generating"
  | "cancelled"
  | "insufficient_data"
  | "failed";

const ANALYSIS_STATUS_COPY: Record<Exclude<AnalysisStatus, "idle">, {
  eyebrow: string;
  title: string;
  description: string;
}> = {
  preparing: {
    eyebrow: "ANALYSIS PREPARING",
    title: "분석 준비 중",
    description: "이번 룩북의 시선 관찰을 안전하게 정리하고 있습니다.",
  },
  requesting: {
    eyebrow: "RECOMMENDATION REQUEST",
    title: "추천 요청 대기 중",
    description: "관찰 데이터를 전달하고 추천 작업을 만들고 있습니다.",
  },
  generating: {
    eyebrow: "RECOMMENDATION IN PROGRESS",
    title: "추천 생성 중",
    description: "결과를 기다리고 있습니다. 시간이 더 걸릴 수 있으며 언제든 취소할 수 있습니다.",
  },
  cancelled: {
    eyebrow: "ANALYSIS CANCELLED",
    title: "추천을 취소했습니다",
    description: "이번 세션의 관찰 데이터는 폐기됐습니다. 다시 시작하면 새 세션으로 진행합니다.",
  },
  insufficient_data: {
    eyebrow: "INSUFFICIENT SIGNAL",
    title: "시선 신호가 충분하지 않아 추천을 만들지 못했습니다",
    description: "다시 체험하려면 새 세션으로 시작해 주세요. 이전 관찰은 재사용하지 않습니다.",
  },
  failed: {
    eyebrow: "RECOMMENDATION UNAVAILABLE",
    title: "추천을 만들지 못했습니다",
    description: "추천 작업을 종료했습니다. 다시 체험하려면 새 세션으로 시작해 주세요.",
  },
};

function RecommendationWaitingScreen({
  status,
  onCancel,
  onRestart,
}: {
  status: Exclude<AnalysisStatus, "idle">;
  onCancel: () => void;
  onRestart: () => void;
}) {
  const copy = ANALYSIS_STATUS_COPY[status];
  const isPending = status === "preparing" || status === "requesting" || status === "generating";

  return (
    <main className="store-screen placeholder-screen analysis-status-screen" role="status">
      <Wordmark />
      <section className="analysis-status-screen__content" aria-live="polite">
        <p className="section-label">{copy.eyebrow}</p>
        <h1>{copy.title}</h1>
        <p>{copy.description}</p>
        {isPending ? (
          <button className="store-button store-button--outline" type="button" onClick={onCancel}>
            추천 취소
          </button>
        ) : (
          <button className="store-button store-button--solid" type="button" onClick={onRestart}>
            새 체험 시작
          </button>
        )}
      </section>
    </main>
  );
}

function ReportScreen({
  recommendation,
  product,
  onHome,
  onRequestManager,
}: {
  recommendation: RecommendationPresentation;
  product: Product | ProductRecommendationItemV2;
  onHome: () => void;
  onRequestManager?: () => Promise<void>;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const [qrFailed, setQrFailed] = useState(false);
  const [requestState, setRequestState] = useState<"idle" | "sending" | "sent" | "failed">(
    "idle",
  );

  const requestManager = async () => {
    if (!onRequestManager || requestState === "sending" || requestState === "sent") return;
    setRequestState("sending");
    try {
      await onRequestManager();
      setRequestState("sent");
    } catch {
      setRequestState("failed");
    }
  };
  const isCentralProduct = "controlled_tags" in product;
  const displayPolicy = resolveProductDisplayPolicy(product);
  const hasApprovedProductDetails = displayPolicy.showProductDetails;

  return (
    <main className="store-screen report-screen">
      <StoreChrome onHome={onHome} step="04" />
      <section className="report-layout">
        <div className="report-media">
          {displayPolicy.imageUrl && !imageFailed ? (
            <img
              src={displayPolicy.imageUrl}
              alt={product.display_name}
              onError={() => setImageFailed(true)}
            />
          ) : (
            <div className="report-media__pending" role="status">
              <strong>상품 정보 준비 중</strong>
              <span>승인된 이미지가 연결된 뒤 표시됩니다.</span>
            </div>
          )}
          <span>{hasApprovedProductDetails ? `TOP 1 · ${product.product_id}` : "TOP 1 · PENDING"}</span>
        </div>
        <div className="report-copy">
          <p className="section-label">YOUR RECOMMENDATION</p>
          <h1>
            {hasApprovedProductDetails
              ? "시선 분석 AI가 선정했습니다"
              : "상품 정보 준비 중"}
          </h1>
          {hasApprovedProductDetails ? (
            <>
              <p className="report-tendency">
                이번 세션의 시선 흐름: {recommendation.tendency}
              </p>
              <h2>{product.display_name}</h2>
              {isCentralProduct && <p className="report-reason">{product.recommendation_summary}</p>}
              <p className="report-reason">{recommendation.reason}</p>
            </>
          ) : (
            <p className="report-reason">
              선정된 상품의 공식 정보와 자산은 담당자 검수 후 표시됩니다. 임의의 이미지나 링크로 대체하지 않습니다.
            </p>
          )}
          {displayPolicy.qrUrl && !qrFailed && (
            <div className="report-qr">
              <img
                src={displayPolicy.qrUrl}
                alt="공식 상품 페이지 QR 코드"
                onError={() => setQrFailed(true)}
              />
              <span>공식 상품 페이지에서 보기</span>
            </div>
          )}
          {recommendation.mode === "mock_v1" && (
            <p className="report-disclaimer">개발 환경에서만 사용하는 v1 Mock fixture 결과입니다.</p>
          )}
          {recommendation.mode === "replay_v2" && (
            <p className="report-disclaimer">
              개발 검증용 replay 파생 신호 결과이며 실제 고객 분석 결과가 아닙니다.
            </p>
          )}
          {recommendation.mode === "demo_fallback_v2" && (
            <p className="report-disclaimer">
              유효 시선이 부족한 로컬 제출 데모 결과이며 실제 시선 기반 추천으로 해석하지 않습니다.
            </p>
          )}
          {displayPolicy.unavailableMessage && (
            <p className="report-disclaimer">
              {displayPolicy.unavailableMessage}
            </p>
          )}
          <p className="report-disclaimer">
            이번 세션의 시선 신호만 사용했으며, 체험이 끝나면 저장하지 않고 폐기합니다.
          </p>
          <div className="report-actions">
            {displayPolicy.officialProductUrl && (
              <a
                className="store-button store-button--solid"
                href={displayPolicy.officialProductUrl}
                rel="noreferrer"
                target="_blank"
              >
                상품 정보 보기
              </a>
            )}
            {displayPolicy.canRequestManager && onRequestManager && (
              <button
                className="store-button store-button--outline"
                type="button"
                disabled={requestState === "sending" || requestState === "sent"}
                onClick={() => void requestManager()}
              >
                {requestState === "sending" && "요청 전송 중"}
                {requestState === "sent" && "매니저 요청 완료"}
                {(requestState === "idle" || requestState === "failed") && "직접 보고 싶어요"}
              </button>
            )}
          </div>
          {requestState === "failed" && (
            <p className="report-request-error" role="alert">
              요청을 전송하지 못했습니다. 다시 시도해 주세요.
            </p>
          )}
          <button className="back-link" type="button" onClick={onHome}>
            ← 처음으로 돌아가기
          </button>
          <span className="sr-only">{recommendation.recommendation_id}</span>
        </div>
      </section>
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
  const [recommendation, setRecommendation] = useState<RecommendationPresentation | null>(null);
  const [recommendedProduct, setRecommendedProduct] = useState<
    Product | ProductRecommendationItemV2 | null
  >(null);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [consentIssue, setConsentIssue] = useState<ConsentIssue | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [cameraState, setCameraState] = useState<CameraDisplayState>("idle");
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatus>("idle");
  const [latestGazeSample, setLatestGazeSample] = useState<GazeSample | null>(null);
  const [latestGazeLayout, setLatestGazeLayout] = useState<VideoLayout | null>(null);
  const [latestGazeReason, setLatestGazeReason] = useState<string | null>(null);
  const [flowController] = useState(() => new AsyncFlowController());
  const gazeSamples = useRef<GazeSample[]>([]);
  const gazeUnavailableSamples = useRef<GazeUnavailableSample[]>([]);
  const videoLayoutsByFrameId = useRef<Map<string, VideoLayout>>(new Map());
  const sessionStartAbortController = useRef<AbortController | null>(null);
  const recommendationAbortController = useRef<AbortController | null>(null);
  const calibrationPromise = useRef<ReturnType<typeof visionClient.startCalibration> | null>(null);
  const calibrationSequence = useRef(0);
  const pollingSessionId = useRef<string | null>(null);

  const abortSessionStart = useCallback(() => {
    sessionStartAbortController.current?.abort();
    sessionStartAbortController.current = null;
  }, []);

  const send = useCallback((event: KioskEvent) => {
    setScreen((currentScreen) => transitionKioskScreen(currentScreen, event));
  }, []);

  useEffect(() => {
    const layoutsByFrameId = videoLayoutsByFrameId.current;
    const removeGazeListener = visionClient.onGazeSample((sample) => {
      gazeSamples.current.push(sample);
      setLatestGazeSample(sample);
      setLatestGazeLayout(layoutsByFrameId.get(sample.frame_id) ?? null);
      setLatestGazeReason(null);
    });
    const removeGazeUnavailableListener =
      "onGazeUnavailable" in visionClient
        ? visionClient.onGazeUnavailable((sample) => {
            if (layoutsByFrameId.has(sample.frame_id)) {
              gazeUnavailableSamples.current.push(sample);
            }
            setLatestGazeSample(null);
            setLatestGazeLayout(null);
            setLatestGazeReason(sample.reason);
          })
        : () => undefined;
    return () => {
      removeGazeListener();
      removeGazeUnavailableListener();
      flowController.invalidateCurrentFlow();
      abortSessionStart();
      recommendationAbortController.current?.abort();
      frameSource.stop();
      layoutsByFrameId.clear();
      void flowController.runSerialized(() => visionClient.stopSession());
    };
  }, [abortSessionStart, flowController]);

  const selectCategory = (category: ProductCategory) => {
    if (category !== "가방") return;

    setSelectedCategory(category);
    setConsentIssue(null);
    send("SELECT_CATEGORY");
  };

  const restart = useCallback(async () => {
    const generation = flowController.invalidateCurrentFlow();
    abortSessionStart();
    recommendationAbortController.current?.abort();
    recommendationAbortController.current = null;
    calibrationPromise.current = null;
    calibrationSequence.current = 0;
    frameSource.stop();
    if (session && screen !== "report") {
      if (useMockApi) void mockApiClient.discardSession(session.session_id);
      else void discardCentralSessionBestEffort(httpApiClient, session.session_id);
    }
    gazeSamples.current.length = 0;
    gazeUnavailableSamples.current.length = 0;
    videoLayoutsByFrameId.current.clear();
    pollingSessionId.current = null;
    setSelectedCategory(null);
    setSession(null);
    setManifest(null);
    setRecommendation(null);
    setRecommendedProduct(null);
    setFlowError(null);
    setConsentIssue(null);
    setIsStarting(false);
    setCameraState("idle");
    setAnalysisStatus("idle");
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
    setLatestGazeReason(null);
    send("RESTART");

    try {
      await flowController.runSerialized(() => visionClient.stopSession());
    } catch {
      if (flowController.isCurrent(generation)) {
        setFlowError("이전 Vision 세션을 종료하지 못했습니다.");
      }
    }
  }, [abortSessionStart, flowController, screen, send, session]);

  const cancelConsent = useCallback(async () => {
    const generation = flowController.invalidateCurrentFlow();
    abortSessionStart();
    recommendationAbortController.current?.abort();
    recommendationAbortController.current = null;
    calibrationPromise.current = null;
    calibrationSequence.current = 0;
    frameSource.stop();
    gazeSamples.current.length = 0;
    gazeUnavailableSamples.current.length = 0;
    videoLayoutsByFrameId.current.clear();
    pollingSessionId.current = null;
    setSelectedCategory(null);
    setSession(null);
    setManifest(null);
    setRecommendation(null);
    setRecommendedProduct(null);
    setFlowError(null);
    setConsentIssue(null);
    setIsStarting(false);
    setCameraState("idle");
    setAnalysisStatus("idle");
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
    setLatestGazeReason(null);
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
    gazeSamples.current.length = 0;
    gazeUnavailableSamples.current.length = 0;
    videoLayoutsByFrameId.current.clear();
    pollingSessionId.current = null;
    setIsStarting(false);
    setCameraState("idle");
    setAnalysisStatus("idle");
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
    setLatestGazeReason(null);
    setConsentIssue("idle-timeout");

    void flowController.runSerialized(() => visionClient.stopSession()).catch(() => {
      if (flowController.isCurrent(generation)) {
        setFlowError("시간 초과 후 Vision 세션을 정리하지 못했습니다.");
      }
    });
  }, [abortSessionStart, flowController]);

  const beginSession = async () => {
    if (!selectedCategory || isStarting || sessionStartAbortController.current) return;

    gazeSamples.current.length = 0;
    gazeUnavailableSamples.current.length = 0;
    videoLayoutsByFrameId.current.clear();
    pollingSessionId.current = null;
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
    setLatestGazeReason(null);
    const generation = flowController.invalidateCurrentFlow();
    const abortController = new AbortController();
    sessionStartAbortController.current = abortController;
    setIsStarting(true);
    setFlowError(null);
    setConsentIssue(null);
    setAnalysisStatus("idle");
    setCameraState("requesting");
    let createdSessionId: string | null = null;

    try {
      await frameSource.open();
      if (!flowController.isCurrent(generation)) {
        frameSource.stop();
        return;
      }
      setCameraState("ready");

      const lookbookId = useMockApi
        ? MOCK_LOOKBOOK_ID_BY_CATEGORY[selectedCategory]
        : configuredLookbookId;
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
          createdSessionId = createdSession.session_id;
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
      if (createdSessionId) {
        if (useMockApi) void mockApiClient.discardSession(createdSessionId);
        else void discardCentralSessionBestEffort(httpApiClient, createdSessionId);
      }
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

  const beginCalibration = useCallback(() => {
    if (calibrationPromise.current) return calibrationPromise.current;
    calibrationSequence.current = 0;
    const promise = flowController.runSerialized(() =>
      visionClient.startCalibration(CALIBRATION_PATTERN),
    );
    calibrationPromise.current = promise;
    return promise;
  }, [flowController]);

  const completeCalibration = useCallback(async () => {
    const generation = flowController.captureGeneration();

    try {
      const result = await beginCalibration();
      if (!flowController.isCurrent(generation)) return;

      // Production live mode is fail-closed: an unavailable Eye worker is not
      // converted into a neutral gaze or a successful calibration.
      if (!result.valid) {
        throw new Error(result.reason ?? "calibration_failed");
      }
      await flowController.runSerialized(() => visionClient.startInference());

      if (flowController.isCurrent(generation)) send("CALIBRATION_SUCCESS");
    } catch (error) {
      calibrationPromise.current = null;
      frameSource.stop();
      if (flowController.isCurrent(generation)) {
        setCameraState("error");
        setFlowError(
          calibrationFailureMessage(error instanceof Error ? error.message : undefined),
        );
      }
    }
  }, [beginCalibration, flowController, send]);

  const captureCalibrationFrame = useCallback(async () => {
    if (!session || !manifest) return;
    const dimensions = frameSource.getVideoDimensions();
    if (!dimensions) return;

    const viewportWidth = Math.max(1, document.documentElement.clientWidth || window.innerWidth);
    const viewportHeight = Math.max(1, document.documentElement.clientHeight || window.innerHeight);
    const layout = calculateContainedVideoLayout({
      viewport_width_px: viewportWidth,
      viewport_height_px: viewportHeight,
      source_width_px: dimensions.width,
      source_height_px: dimensions.height,
      element_rect: {
        x_px: 0,
        y_px: 0,
        width_px: viewportWidth,
        height_px: viewportHeight,
      },
    });
    const sequence = calibrationSequence.current;
    calibrationSequence.current += 1;
    const context = createFrameContext({
      session_id: session.session_id,
      sequence,
      frame_id: `calibration-frame-${String(sequence).padStart(8, "0")}`,
      captured_at_mono_ms: performance.now(),
      video_id: manifest.video_id,
      video_time_seconds: 0,
      playback_epoch: 0,
      layout,
    });

    await frameSource.capture(context, async (frame, frameContext, signal) => {
      await visionClient.sendFrame(frame, frameContext, { signal });
    });
  }, [manifest, session]);

  const completeLookbook = useCallback(async () => {
    const generation = flowController.captureGeneration();
    if (!session || !manifest) {
      setFlowError("진행 중인 세션 정보를 찾지 못했습니다.");
      return;
    }

    recommendationAbortController.current?.abort();
    const abortController = new AbortController();
    recommendationAbortController.current = abortController;
    frameSource.stop();
    setCameraState("idle");
    pollingSessionId.current = null;
    setAnalysisStatus("preparing");
    send("LOOKBOOK_FINISHED");

    try {
      await flowController.runSerialized(() => visionClient.stopSession());
      if (!flowController.isCurrent(generation)) return;
      setAnalysisStatus("requesting");

      if (useMockApi) {
        const batches = buildD1ReactionBatches({
          batchId: `batch-${session.session_id}-0001`,
          batchSequence: 0,
          sessionId: session.session_id,
          manifest,
          gazeSamples: gazeSamples.current,
          expressionSamples: [],
          videoLayoutsByFrameId: videoLayoutsByFrameId.current,
        });
        for (const batch of batches) {
          if (!flowController.isCurrent(generation)) return;
          await mockApiClient.appendReactionBatch(session.session_id, batch);
        }
        await apiClient.completeSessionAnalysis(session.session_id, {
          signal: abortController.signal,
        });
      } else {
        const batches = buildObservationBatchesV2({
          batchId: `observation-${session.session_id}-0001`,
          batchSequence: 0,
          sessionId: session.session_id,
          manifest,
          gazeSamples: gazeSamples.current,
          gazeUnavailableSamples: gazeUnavailableSamples.current,
          expressionSamples: [],
          videoLayoutsByFrameId: videoLayoutsByFrameId.current,
        });
        await submitCentralRecommendation(
          httpApiClient,
          session.session_id,
          batches,
          abortController.signal,
        );
      }

      if (!flowController.isCurrent(generation)) return;
      setAnalysisStatus("generating");
    } catch {
      if (useMockApi) {
        void mockApiClient.discardSession(session.session_id);
      } else {
        void discardCentralSessionBestEffort(httpApiClient, session.session_id);
      }
      if (flowController.isCurrent(generation) && !abortController.signal.aborted) {
        setAnalysisStatus("failed");
      }
    } finally {
      if (recommendationAbortController.current === abortController) {
        recommendationAbortController.current = null;
      }
      if (flowController.isCurrent(generation)) {
        gazeSamples.current.length = 0;
        gazeUnavailableSamples.current.length = 0;
        videoLayoutsByFrameId.current.clear();
        pollingSessionId.current = null;
        setLatestGazeSample(null);
        setLatestGazeLayout(null);
        setLatestGazeReason(null);
      }
    }
  }, [flowController, manifest, send, session]);

  const captureCameraFrame = useCallback(
    async (contextFactory: () => FrameContext) => {
      const generation = flowController.captureGeneration();

      try {
        await frameSource.capture(
          () => {
            const context = contextFactory();
            rememberCapturedFrameLayout(videoLayoutsByFrameId.current, context);
            return context;
          },
          async (frame, frameContext, signal) => {
            const delivery = await visionClient.sendFrame(frame, frameContext, { signal });
            const hasGazeResult = gazeSamples.current.some(
              (sample) => sample.frame_id === frameContext.frame_id,
            );
            const hasUnavailableResult = gazeUnavailableSamples.current.some(
              (sample) => sample.frame_id === frameContext.frame_id,
            );
            if (!hasGazeResult && !hasUnavailableResult) {
              gazeUnavailableSamples.current.push({
                session_id: frameContext.session_id,
                sequence: frameContext.sequence,
                frame_id: frameContext.frame_id,
                captured_at_mono_ms: frameContext.captured_at_mono_ms,
                video_id: frameContext.video_id,
                video_time_ms: frameContext.video_time_ms,
                playback_epoch: frameContext.playback_epoch,
                reason: delivery.reason ?? "not_observed",
              });
            }
          },
        );
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
      setFlowError("추천에 필요한 세션 정보를 찾지 못했습니다.");
      return;
    }

    recommendationAbortController.current?.abort();
    const abortController = new AbortController();
    recommendationAbortController.current = abortController;

    try {
      if (!flowController.isCurrent(generation)) return;
      let presentation: RecommendationPresentation;
      let product: Product | ProductRecommendationItemV2;
      if (useMockApi) {
        const result = await pollRecommendation<RecommendationResult>({
          signal: abortController.signal,
          load: (signal) =>
            apiClient.getSessionRecommendation(session.session_id, { signal }),
        });
        if (result.status !== "completed") {
          throw new Error("Mock fixture did not return a completed result.");
        }
        presentation = presentMockRecommendation(result);
        product = await mockApiClient.getProduct(presentation.product_id);
      } else {
        type CentralPollResult =
          | RecommendationDecisionV2
          | (RecommendationAcceptedV2 & { reason: null });
        const decision = await pollRecommendation<CentralPollResult>({
          signal: abortController.signal,
          load: async (signal) => {
            const result = await httpApiClient.getCentralRecommendation(
              session.session_id,
              { signal },
            );
            return result.status === "pending" ? { ...result, reason: null } : result;
          },
        });
        if (decision.status !== "completed") {
          throw new Error("Central recommendation did not return a completed decision.");
        }
        if (!decision.selected_product_id) {
          throw new Error("Completed central recommendation has no selected product.");
        }
        product = await httpApiClient.getCentralProduct(decision.selected_product_id);
        presentation = presentCentralRecommendation(decision, product);
      }
      if (!flowController.isCurrent(generation)) return;

      if (flowController.isCurrent(generation)) {
        setRecommendation(presentation);
        setRecommendedProduct(product);
        send("RECOMMENDATION_READY");
      }
    } catch (error: unknown) {
      if (abortController.signal.aborted) return;
      if (useMockApi) {
        void mockApiClient.discardSession(session.session_id);
      } else {
        void discardCentralSessionBestEffort(httpApiClient, session.session_id);
      }
      if (flowController.isCurrent(generation)) {
        setAnalysisStatus(
          error instanceof RecommendationPollingError && error.code === "insufficient_data"
            ? "insufficient_data"
            : "failed",
        );
      }
    } finally {
      if (recommendationAbortController.current === abortController) {
        recommendationAbortController.current = null;
      }
    }
  }, [flowController, send, session]);

  useEffect(() => {
    if (screen !== "finalizing" || analysisStatus !== "generating" || !session) return;
    if (pollingSessionId.current === session.session_id) return;
    pollingSessionId.current = session.session_id;
    void loadRecommendation();
  }, [analysisStatus, loadRecommendation, screen, session]);

  const cancelRecommendation = useCallback(async () => {
    const generation = flowController.invalidateCurrentFlow();
    recommendationAbortController.current?.abort();
    recommendationAbortController.current = null;
    pollingSessionId.current = null;
    frameSource.stop();
    gazeSamples.current.length = 0;
    gazeUnavailableSamples.current.length = 0;
    videoLayoutsByFrameId.current.clear();
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
    setLatestGazeReason(null);
    setCameraState("idle");
    setAnalysisStatus("cancelled");

    if (session) {
      if (useMockApi) void mockApiClient.discardSession(session.session_id);
      else void discardCentralSessionBestEffort(httpApiClient, session.session_id);
    }
    try {
      await flowController.runSerialized(() => visionClient.stopSession());
    } catch {
      if (flowController.isCurrent(generation)) setAnalysisStatus("cancelled");
    }
  }, [flowController, session]);

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
    return (
      <Calibration
        onBegin={beginCalibration}
        onComplete={completeCalibration}
        onFrameCapture={captureCalibrationFrame}
        onHome={restart}
      />
    );
  }

  if (screen === "lookbook") {
    if (!session || !manifest) {
      return (
        <ErrorPlaceholder
          message="룩북 재생에 필요한 세션 정보를 찾지 못했습니다."
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
        debugEnabled={enableAoiDebugOverlay}
        debugGazeLayout={latestGazeLayout}
        debugGazeReason={latestGazeReason}
        debugGazeSample={latestGazeSample}
        posterUrl={getLookbookPoster(selectedCategory)}
        sessionId={session.session_id}
        videoId={manifest.video_id}
        videoUrl={configuredLookbookVideoUrl}
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
      <RecommendationWaitingScreen
        status={analysisStatus === "idle" ? "preparing" : analysisStatus}
        onCancel={() => void cancelRecommendation()}
        onRestart={() => void restart()}
      />
    );
  }

  if (screen === "report" && recommendation && recommendedProduct && session) {
    return (
      <ReportScreen
        recommendation={recommendation}
        product={recommendedProduct}
        onHome={restart}
        onRequestManager={() => {
          const managerRequest = buildManagerProductRequestV2(
            session.session_id,
            recommendation.recommendation_id,
            recommendation.product_id,
          );
          return (useMockApi
            ? mockApiClient.requestManagerProduct(session.session_id, {
                request_id: managerRequest.request_id,
                recommendation_id: managerRequest.recommendation_id,
              })
            : httpApiClient.requestCentralManagerProduct(
                session.session_id,
                managerRequest,
              )
          ).then(() => undefined);
        }}
      />
    );
  }

  return (
    <main className="store-screen placeholder-screen">
      <Wordmark />
      <p>다음 화면을 준비 중입니다.</p>
    </main>
  );
}

export default App;
