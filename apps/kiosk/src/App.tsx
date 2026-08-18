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
  INITIAL_KIOSK_SCREEN,
  transitionKioskScreen,
  type KioskEvent,
} from "./app/kiosk-machine.ts";
import { buildManagerProductRequestV2 } from "./app/manager-product-request-v2.ts";
import {
  buildObservationBatchesV2,
  resolveObservationAttentionAuthority,
} from "./app/observation-batch-v2.ts";
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
import type { FrameContext, VideoLayout } from "./app/video-context.ts";
import type {
  ExpressionSample,
  GazeSample,
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

const productCategories: CategoryOption[] = useMockApi
  ? mockProductCategories
  : [mockProductCategories[0]];

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
                <strong>현재는 local/replay 분석 경계를 사용합니다</strong>
                <span>
                  원본 프레임은 중앙 추천 서버로 보내지 않으며 정형화된 시선·표정 파생
                  JSON만 Backend에 전달합니다.
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
                  생성 후 폐기합니다. 최종 추천은 최소 운영 metadata만 Backend 정책에 따라
                  처리합니다.
                </span>
              </dd>
            </div>
          </dl>

          <div className="consent-meta">
            <span>CENTRAL V2 · LOCAL IN-PROCESS REPLAY VISION</span>
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

function ReportScreen({
  recommendation,
  product,
  onHome,
  onRequestManager,
}: {
  recommendation: RecommendationPresentation;
  product: Product | ProductRecommendationItemV2;
  onHome: () => void;
  onRequestManager: () => Promise<void>;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const [requestState, setRequestState] = useState<"idle" | "sending" | "sent" | "failed">(
    "idle",
  );

  const requestManager = async () => {
    if (requestState === "sending" || requestState === "sent") return;
    setRequestState("sending");
    try {
      await onRequestManager();
      setRequestState("sent");
    } catch {
      setRequestState("failed");
    }
  };
  const isCentralProduct = "controlled_tags" in product;
  const imageUrl = isCentralProduct
    ? product.approved_asset && product.image_asset_path
      ? `/${product.image_asset_path}`
      : null
    : product.image_url;
  const productUrl = isCentralProduct
    ? (product.official_product_url ?? product.official_listing_url)
    : product.product_url;

  return (
    <main className="store-screen report-screen">
      <StoreChrome onHome={onHome} step="04" />
      <section className="report-layout">
        <div className="report-media">
          <img
            src={imageFailed || !imageUrl ? bagImage : imageUrl}
            alt={product.display_name}
            onError={() => setImageFailed(true)}
          />
          <span>TOP 1 · {product.product_id}</span>
        </div>
        <div className="report-copy">
          <p className="section-label">YOUR RECOMMENDATION</p>
          <h1>말로 표현되지 않은 탐색 반응에서 발견한 추천</h1>
          <p className="report-tendency">
            이번 세션의 스타일 탐색 경향: {recommendation.tendency}
          </p>
          <h2>{product.display_name}</h2>
          <p className="report-reason">{recommendation.reason}</p>
          {recommendation.mode === "mock_v1" && (
            <p className="report-disclaimer">개발 환경에서만 사용하는 v1 Mock fixture 결과입니다.</p>
          )}
          {recommendation.mode === "replay_v2" && (
            <p className="report-disclaimer">
              개발 검증용 replay 파생 신호 결과이며 실제 고객 분석 결과가 아닙니다.
            </p>
          )}
          {isCentralProduct && !product.approved_asset && (
            <p className="report-disclaimer">
              검수된 상품 이미지와 개별 QR은 아직 연결되지 않아 기본 이미지를 표시합니다.
            </p>
          )}
          <p className="report-disclaimer">
            시선·표정 관련 신호는 이번 세션의 비언어적 관찰값이며 감정·성격·구매
            의도를 확정하지 않습니다.
          </p>
          <div className="report-actions">
            <a
              className="store-button store-button--solid"
              href={productUrl}
              rel="noreferrer"
              target="_blank"
            >
              {isCentralProduct && !product.official_product_url
                ? "공식 가방 목록 보기"
                : "상품 정보 보기"}
            </a>
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
  const [latestGazeSample, setLatestGazeSample] = useState<GazeSample | null>(null);
  const [latestGazeLayout, setLatestGazeLayout] = useState<VideoLayout | null>(null);
  const [flowController] = useState(() => new AsyncFlowController());
  const gazeSamples = useRef<GazeSample[]>([]);
  const videoLayoutsByFrameId = useRef<Map<string, VideoLayout>>(new Map());
  const expressionSamples = useRef<ExpressionSample[]>([]);
  const sessionStartAbortController = useRef<AbortController | null>(null);
  const recommendationAbortController = useRef<AbortController | null>(null);

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
    });
    const removeExpressionListener = visionClient.onExpressionSample((sample) => {
      expressionSamples.current.push(sample);
    });

    return () => {
      removeGazeListener();
      removeExpressionListener();
      flowController.invalidateCurrentFlow();
      abortSessionStart();
      recommendationAbortController.current?.abort();
      frameSource.stop();
      layoutsByFrameId.clear();
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
    recommendationAbortController.current?.abort();
    recommendationAbortController.current = null;
    frameSource.stop();
    if (session && screen !== "report") {
      if (useMockApi) void mockApiClient.discardSession(session.session_id);
      else void discardCentralSessionBestEffort(httpApiClient, session.session_id);
    }
    gazeSamples.current.length = 0;
    videoLayoutsByFrameId.current.clear();
    expressionSamples.current.length = 0;
    setSelectedCategory(null);
    setSession(null);
    setManifest(null);
    setRecommendation(null);
    setRecommendedProduct(null);
    setFlowError(null);
    setConsentIssue(null);
    setIsStarting(false);
    setCameraState("idle");
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
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
    frameSource.stop();
    gazeSamples.current.length = 0;
    videoLayoutsByFrameId.current.clear();
    expressionSamples.current.length = 0;
    setSelectedCategory(null);
    setSession(null);
    setManifest(null);
    setRecommendation(null);
    setRecommendedProduct(null);
    setFlowError(null);
    setConsentIssue(null);
    setIsStarting(false);
    setCameraState("idle");
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
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
    videoLayoutsByFrameId.current.clear();
    expressionSamples.current.length = 0;
    setIsStarting(false);
    setCameraState("idle");
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
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
    videoLayoutsByFrameId.current.clear();
    expressionSamples.current.length = 0;
    setLatestGazeSample(null);
    setLatestGazeLayout(null);
    const generation = flowController.invalidateCurrentFlow();
    const abortController = new AbortController();
    sessionStartAbortController.current = abortController;
    setIsStarting(true);
    setFlowError(null);
    setConsentIssue(null);
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

  const completeCalibration = useCallback(async () => {
    const generation = flowController.captureGeneration();

    try {
      const result = await flowController.runSerialized(() =>
        visionClient.startCalibration(calibrationPattern),
      );
      if (!flowController.isCurrent(generation)) return;

      // The merged localhost Gateway is intentionally Face-only. EyeTrax is not
      // connected yet, so its explicit calibration absence must not block the
      // MediaPipe live slice. A future Eye-connected Gateway must return valid=true.
      const faceOnlyCalibration =
        configuredVisionMode === "live" && result.reason === "eye_not_connected";
      if (!result.valid && !faceOnlyCalibration) {
        throw new Error(result.reason ?? "calibration_failed");
      }
      await flowController.runSerialized(() => visionClient.startInference());

      if (flowController.isCurrent(generation)) send("CALIBRATION_SUCCESS");
    } catch {
      frameSource.stop();
      if (flowController.isCurrent(generation)) {
        setCameraState("error");
        setFlowError("로컬 시선 보정을 완료하지 못했습니다.");
      }
    }
  }, [flowController, send]);

  const completeLookbook = useCallback(async () => {
    const generation = flowController.captureGeneration();
    recommendationAbortController.current?.abort();
    const abortController = new AbortController();
    recommendationAbortController.current = abortController;
    frameSource.stop();
    setCameraState("idle");

    if (!session || !manifest) {
      setFlowError("진행 중인 세션 정보를 찾지 못했습니다.");
      return;
    }

    try {
      await flowController.runSerialized(() => visionClient.stopSession());
      if (!flowController.isCurrent(generation)) return;

      if (useMockApi) {
        const batches = buildD1ReactionBatches({
          batchId: `batch-${session.session_id}-0001`,
          batchSequence: 0,
          sessionId: session.session_id,
          manifest,
          gazeSamples: gazeSamples.current,
          expressionSamples: expressionSamples.current,
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
          attentionAuthority: resolveObservationAttentionAuthority(manifest),
          gazeSamples: gazeSamples.current,
          expressionSamples: expressionSamples.current,
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
      if (flowController.isCurrent(generation)) send("LOOKBOOK_FINISHED");
    } catch {
      if (!useMockApi) {
        void discardCentralSessionBestEffort(httpApiClient, session.session_id);
      }
      if (flowController.isCurrent(generation) && !abortController.signal.aborted) {
        setFlowError("룩북 분석을 완료하지 못했습니다.");
      }
    } finally {
      if (recommendationAbortController.current === abortController) {
        recommendationAbortController.current = null;
      }
      if (flowController.isCurrent(generation)) {
        gazeSamples.current.length = 0;
        videoLayoutsByFrameId.current.clear();
        expressionSamples.current.length = 0;
        setLatestGazeSample(null);
        setLatestGazeLayout(null);
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
            await visionClient.sendFrame(frame, frameContext, { signal });
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
        presentation = {
          ...presentCentralRecommendation(decision, product),
          mode: "replay_v2",
        };
      }
      if (!flowController.isCurrent(generation)) return;

      if (flowController.isCurrent(generation)) {
        setRecommendation(presentation);
        setRecommendedProduct(product);
        send("RECOMMENDATION_READY");
      }
    } catch (error: unknown) {
      if (abortController.signal.aborted) return;
      if (!useMockApi) {
        void discardCentralSessionBestEffort(httpApiClient, session.session_id);
      }
      if (flowController.isCurrent(generation)) {
        setFlowError(
          error instanceof RecommendationPollingError
            ? error.message
            : "추천 결과를 불러오지 못했습니다.",
        );
      }
    } finally {
      if (recommendationAbortController.current === abortController) {
        recommendationAbortController.current = null;
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
        debugGazeSample={latestGazeSample}
        manifest={manifest}
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
      <TimedPlaceholder
        message="시선과 표정 관련 관찰 신호를 바탕으로 추천을 준비하고 있습니다."
        onComplete={loadRecommendation}
        onHome={restart}
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
