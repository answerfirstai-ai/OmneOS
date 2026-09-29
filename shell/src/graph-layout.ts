/** Place graph nodes that the backend actually returned. */

export interface GraphNode {
  id: string;
  type: string;
  label: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  type: string;
}

export interface PlacedNode extends GraphNode {
  column: number;
  x: number;
  y: number;
}

export interface GraphLayout {
  nodes: PlacedNode[];
  edges: GraphEdge[];
}

export interface GraphCamera {
  x: number;
  y: number;
  scale: number;
  selectedId: string | null;
}

const COLUMN: Record<string, number> = {
  core: 0,
  project: 1,
  mission: 2,
  objective: 2,
  task: 3,
  worker: 4,
  agent: 5,
  model: 6,
  tool: 7,
  resource: 8,
};

/** Lay out payload nodes. Edges are copied and no extra nodes are created. */
export function layoutGraph(nodes: readonly GraphNode[], edges: readonly GraphEdge[]): GraphLayout {
  const groups = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const column = COLUMN[node.type] ?? 9;
    const list = groups.get(column) ?? [];
    list.push(node);
    groups.set(column, list);
  }
  const placed: PlacedNode[] = [];
  for (const [column, list] of [...groups.entries()].sort((left, right) => left[0] - right[0])) {
    list.forEach((node, row) => {
      placed.push({
        id: node.id,
        type: node.type,
        label: node.label,
        column,
        x: column * 150 + 28,
        y: row * 56 + 28,
      });
    });
  }
  return {
    nodes: placed,
    edges: edges.map((edge) => ({ from: edge.from, to: edge.to, type: edge.type })),
  };
}

export function readGraph(payload: unknown): GraphLayout {
  const record = isRecord(payload) ? payload : {};
  const nodes = Array.isArray(record["nodes"]) ? record["nodes"].flatMap(readNode) : [];
  const edges = Array.isArray(record["edges"]) ? record["edges"].flatMap(readEdge) : [];
  return layoutGraph(nodes, edges);
}

export function graphKey(layout: GraphLayout, statuses: ReadonlyMap<string, string>): string {
  const marks = layout.nodes.map((node) => `${node.id}:${statuses.get(node.id) ?? ""}`);
  const edges = layout.edges.map((edge) => `${edge.from}>${edge.to}:${edge.type}`);
  return `${marks.join("|")}#${edges.join("|")}`;
}

export function initialCamera(): GraphCamera {
  return { x: 16, y: 16, scale: 1, selectedId: null };
}

export function panCamera(camera: GraphCamera, dx: number, dy: number): GraphCamera {
  return { ...camera, x: camera.x + dx, y: camera.y + dy };
}

export function zoomCamera(camera: GraphCamera, factor: number): GraphCamera {
  const scale = Math.min(2.5, Math.max(0.4, Number((camera.scale * factor).toFixed(3))));
  return { ...camera, scale };
}

export function selectGraphNode(camera: GraphCamera, id: string | null): GraphCamera {
  return { ...camera, selectedId: id };
}

export function cameraForNode(
  camera: GraphCamera,
  node: { x: number; y: number } | null,
  viewport: { width: number; height: number },
): GraphCamera {
  if (node === null) {
    return camera;
  }
  return {
    ...camera,
    x: viewport.width / 2 - node.x * camera.scale,
    y: viewport.height / 2 - node.y * camera.scale,
  };
}

export function graphStatuses(input: {
  missions: readonly { id: string; status: string }[];
  activity: readonly { id: string; status: string }[];
  workers: readonly { worker_id: string; status: string }[];
}): Map<string, string> {
  const statuses = new Map<string, string>();
  for (const mission of input.missions) {
    statuses.set(mission.id, mission.status);
  }
  for (const task of input.activity) {
    statuses.set(task.id, task.status);
  }
  for (const worker of input.workers) {
    statuses.set(worker.worker_id, worker.status);
  }
  return statuses;
}

function readNode(value: unknown): GraphNode[] {
  if (!isRecord(value)) {
    return [];
  }
  if (
    typeof value["id"] !== "string" ||
    typeof value["type"] !== "string" ||
    typeof value["label"] !== "string"
  ) {
    return [];
  }
  return [{ id: value["id"], type: value["type"], label: value["label"] }];
}

function readEdge(value: unknown): GraphEdge[] {
  if (!isRecord(value)) {
    return [];
  }
  if (
    typeof value["from"] !== "string" ||
    typeof value["to"] !== "string" ||
    typeof value["type"] !== "string"
  ) {
    return [];
  }
  return [{ from: value["from"], to: value["to"], type: value["type"] }];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
