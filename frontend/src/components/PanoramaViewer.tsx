"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import "pannellum/build/pannellum.css";

import type { PublicTablePinOut } from "@/lib/api";
import { mapPinsToHotspots } from "@/lib/panorama";
import type { PannellumViewerInstance } from "@/types/pannellum";

export interface PanoramaViewerProps {
  imageUrl: string;
  pins: PublicTablePinOut[];
  selectedPinId: number | null;
  onSelectPin: (pin: PublicTablePinOut | null) => void;
}

function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(
      window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
    );
  } catch {
    return false;
  }
}

export default function PanoramaViewer({
  imageUrl,
  pins,
  selectedPinId,
  onSelectPin,
}: PanoramaViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<PannellumViewerInstance | null>(null);
  const onSelectPinRef = useRef(onSelectPin);
  const pointerDownPosRef = useRef<{ x: number; y: number } | null>(null);

  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [errorState, setErrorState] = useState<{ url: string; message: string } | null>(null);

  const webglSupported = useMemo(() => isWebGLAvailable(), []);
  const hotspots = useMemo(() => mapPinsToHotspots(pins), [pins]);
  const loadError = errorState?.url === imageUrl ? errorState.message : null;
  const loading = webglSupported && loadedUrl !== imageUrl && loadError === null;

  useEffect(() => {
    onSelectPinRef.current = onSelectPin;
  }, [onSelectPin]);

  useEffect(() => {
    const buttons = containerRef.current?.querySelectorAll<HTMLButtonElement>("[data-pin-id]");
    buttons?.forEach((btn) => {
      const isSelected = Number(btn.dataset.pinId) === selectedPinId;
      btn.setAttribute("aria-pressed", String(isSelected));
      if (isSelected) {
        btn.classList.add("ring-4", "ring-amber-400", "bg-amber-600");
        btn.classList.remove("bg-stone-900/90");
      } else {
        btn.classList.remove("ring-4", "ring-amber-400", "bg-amber-600");
        btn.classList.add("bg-stone-900/90");
      }
    });
  }, [selectedPinId, loadedUrl]);

  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container || !webglSupported) return;

    async function initViewer() {
      try {
        await import("pannellum/build/pannellum.js");
        if (cancelled || !container || !window.pannellum) return;

        viewerRef.current?.destroy();
        viewerRef.current = null;

        const viewer = window.pannellum.viewer(container, {
          type: "equirectangular",
          panorama: imageUrl,
          autoLoad: true,
          showControls: true,
          compass: false,
          hfov: 95,
          minHfov: 50,
          maxHfov: 120,
          hotSpots: hotspots.map((hs, index) => ({
            id: hs.id,
            pitch: hs.pitch,
            yaw: hs.yaw,
            type: "info",
            createTooltipFunc: (hotSpotDiv: HTMLElement) => {
              hotSpotDiv.classList.add("mizban-pin-hotspot");
              hotSpotDiv.style.pointerEvents = "auto";
              hotSpotDiv.innerHTML = "";

              const btn = document.createElement("button");
              btn.type = "button";
              btn.dataset.pinId = String(hs.pinId);
              btn.setAttribute("aria-label", `میز ${hs.label}`);
              btn.className =
                "flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-full border-2 border-white bg-stone-900/90 px-3 py-1.5 text-xs font-bold text-white shadow-lg transition hover:scale-105 focus:outline-none";
              btn.textContent = `${index + 1}. ${hs.label}`;

              btn.addEventListener("click", (e) => {
                e.stopPropagation();
                onSelectPinRef.current(hs.pin);
              });

              hotSpotDiv.appendChild(btn);
            },
          })),
        });

        viewer.on("load", () => {
          if (!cancelled) {
            setLoadedUrl(imageUrl);
            setErrorState(null);
          }
        });

        viewer.on("error", () => {
          if (!cancelled) {
            setErrorState({
              url: imageUrl,
              message: "بارگذاری تصویر ۳۶۰ درجه با خطا مواجه شد.",
            });
          }
        });

        viewerRef.current = viewer;
      } catch {
        if (!cancelled) {
          setErrorState({
            url: imageUrl,
            message: "راه‌اندازی نمایشگر ۳۶۰ درجه با خطا مواجه شد.",
          });
        }
      }
    }

    void initViewer();

    return () => {
      cancelled = true;
      viewerRef.current?.destroy();
      viewerRef.current = null;
    };
  }, [imageUrl, hotspots, webglSupported]);

  if (!webglSupported) {
    return (
      <div
        role="alert"
        className="flex h-80 items-center justify-center rounded-xl border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-900"
      >
        مرورگر یا دستگاه شما از نمایشگر سه‌بعدی (WebGL) پشتیبانی نمی‌کند.
      </div>
    );
  }

  return (
    <div
      className="relative h-[380px] w-full overflow-hidden rounded-xl border border-stone-200 bg-stone-900 sm:h-[480px]"
      onPointerDown={(e) => {
        pointerDownPosRef.current = { x: e.clientX, y: e.clientY };
      }}
      onPointerUp={(e) => {
        const target = e.target as HTMLElement | null;
        if (target?.closest(".mizban-pin-hotspot") || target?.closest(".pnlm-controls-container")) {
          return;
        }
        const start = pointerDownPosRef.current;
        if (!start) return;
        const dx = Math.abs(e.clientX - start.x);
        const dy = Math.abs(e.clientY - start.y);
        if (dx < 6 && dy < 6) {
          onSelectPin(null);
        }
      }}
    >
      <div ref={containerRef} className="h-full w-full" />

      {loading ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-stone-900/75 text-sm text-white">
          در حال بارگذاری نمای ۳۶۰ درجه...
        </div>
      ) : null}

      {loadError ? (
        <div
          role="alert"
          className="absolute inset-0 flex items-center justify-center bg-stone-900/90 p-6 text-center text-sm text-red-200"
        >
          {loadError}
        </div>
      ) : null}
    </div>
  );
}
