/** Show the current mission neighborhood. Shared agents do not pull in other missions. */

import { layoutGraph, type GraphLayout, type GraphNode } from "./graph-layout.js";

const HUBS = new Set(["core", "agent", "model", "tool"]);

/** Keep the core when nothing is active. Otherwise keep the mission and nodes tied to it. */
export function focusGraph(layout: GraphLayout, missionId: string | null): GraphLayout {
  const nodes = selectedNodes(layout, missionId);
  const ids = new Set(nodes.map((node) => node.id));
  const edges = layout.edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to));
  return layoutGraph(nodes, edges);
}

function selectedNodes(layout: GraphLayout, missionId: string | null): GraphNode[] {
  const core = layout.nodes.find((node) => node.type === "core" || node.id === "core");
  if (missionId === null) {
    return core === undefined ? [] : [plain(core)];
  }
  const mission = layout.nodes.find((node) => node.id === missionId);
  if (mission === undefined) {
    return core === undefined ? [] : [plain(core)];
  }
  const included = new Set<string>([mission.id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const edge of layout.edges) {
      const next = expand(edge.from, edge.to, included, layout, missionId);
      if (next !== null && !included.has(next)) {
        included.add(next);
        grew = true;
      }
    }
  }
  return layout.nodes.filter((node) => included.has(node.id)).map(plain);
}

function expand(
  from: string,
  to: string,
  included: ReadonlySet<string>,
  layout: GraphLayout,
  missionId: string,
): string | null {
  const anchorId = included.has(from) ? from : included.has(to) ? to : null;
  if (anchorId === null) {
    return null;
  }
  const otherId = anchorId === from ? to : from;
  if (included.has(otherId)) {
    return null;
  }
  const anchor = layout.nodes.find((node) => node.id === anchorId);
  const other = layout.nodes.find((node) => node.id === otherId);
  if (anchor === undefined || other === undefined) {
    return null;
  }
  if (HUBS.has(anchor.type)) {
    return null;
  }
  if (other.type === "mission" && other.id !== missionId) {
    return null;
  }
  return other.id;
}

function plain(node: GraphNode): GraphNode {
  return { id: node.id, type: node.type, label: node.label };
}
