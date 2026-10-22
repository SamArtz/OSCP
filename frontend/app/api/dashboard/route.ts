import { forward } from "@/lib/proxy";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  return forward(request, `/api/v1/dashboard/metrics${new URL(request.url).search}`);
}
export async function POST(request: Request) {
  return forward(request, `/api/v1/dashboard/metrics${new URL(request.url).search}`);
}
