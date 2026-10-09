/** Contract section 13 fixtures (copied verbatim into JSON files). Frontend dev/testing only. */
import type {
  Alert,
  AppConfig,
  Envelope,
  FrameResult,
  GuardianMessageToUserPayload,
  Session,
  UserStatusPayload,
} from "@/types/contracts";
import vehicleRightEnv from "./frame_result.vehicle_right.json";
import criticalObstacle from "./frame_result.critical_obstacle.json";
import clear from "./frame_result.clear.json";
import alertEmergency from "./alert.emergency.json";
import guardianMessageEnv from "./guardian_message.json";
import userStatusEnv from "./user_status.json";
import session from "./session.json";
import appConfig from "./config.json";

export const fixtures = {
  vehicleRight: vehicleRightEnv as Envelope<FrameResult>,
  criticalObstacle: criticalObstacle as FrameResult,
  clear: clear as FrameResult,
  alertEmergency: alertEmergency as Alert,
  guardianMessage: guardianMessageEnv as Envelope<GuardianMessageToUserPayload>,
  userStatus: userStatusEnv as Envelope<UserStatusPayload>,
  session: session as Session,
  config: appConfig as unknown as AppConfig,
};

/** Scenario played in a loop by the mock client: ~3 s per scene. */
export const MOCK_SCENES: FrameResult[] = [
  fixtures.vehicleRight.payload,
  fixtures.clear,
  fixtures.criticalObstacle,
  fixtures.clear,
];
export const SCENE_MS = 3000;

export function currentScene(now = Date.now()): FrameResult {
  return MOCK_SCENES[Math.floor(now / SCENE_MS) % MOCK_SCENES.length] ?? fixtures.clear;
}

export function mockId(): string {
  return crypto.randomUUID();
}
