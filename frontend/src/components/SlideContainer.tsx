import React from "react";
import { Slide } from "./Slide";
import type { Slide as SlideType } from "../types/slide";
import "./SlideContainer.css";

interface SlideContainerProps {
  slides: SlideType[];
  currentSlideIndex: number;
}

export const SlideContainer: React.FC<SlideContainerProps> = ({
  slides,
  currentSlideIndex,
}) => {
  if (slides.length === 0) {
    return (
      <div className="slide-container">
        <div className="slide-placeholder">
          <p>No slides available. Start a presentation to generate slides.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="slide-container">
      <div className="slide-navigation-indicator">
        Slide {currentSlideIndex + 1} of {slides.length}
      </div>
      {slides.map((slide, index) => (
        <Slide
          key={slide.id}
          slide={slide}
          isActive={index === currentSlideIndex}
        />
      ))}
    </div>
  );
};




