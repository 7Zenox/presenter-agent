import React from "react";
import type { Slide as SlideType } from "../types/slide";
import "./Slide.css";

interface SlideProps {
  slide: SlideType;
  isActive: boolean;
}

export const Slide: React.FC<SlideProps> = ({ slide, isActive }) => {
  return (
    <div className={`slide ${isActive ? "slide-active" : "slide-inactive"}`}>
      <h2 className="slide-title">{slide.title}</h2>
      <ul className="slide-bullets">
        {slide.bullets.map((bullet, index) => (
          <li key={index}>{bullet}</li>
        ))}
      </ul>
    </div>
  );
};




