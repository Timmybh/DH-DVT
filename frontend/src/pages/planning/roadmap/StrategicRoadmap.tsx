import { useAuth } from "../../../context/AuthContext";
import CeoRoadmapPage from "./CeoRoadmapPage";

/** Entry point route /planning/roadmap — trang chủ Strategic Roadmap (thay cho tab CEO Roadmap cũ). */
export default function StrategicRoadmap() {
  const { can } = useAuth();
  return <CeoRoadmapPage perm={{ manage: can("roadmap.manage") }} />;
}
