import { describe, expect, it } from "vitest"
import { aircraftPhotoUrl, parseAircraftPhoto } from "./aircraftPhoto"

describe("where to ask for a photo", () => {
  it("asks by ICAO hex, lower-cased, which is the id the transponder sends", () => {
    expect(aircraftPhotoUrl("43C6E2")).toBe(
      "https://api.planespotters.net/pub/photos/hex/43c6e2",
    )
  })

  //: No hex, no question. The other identifiers on the row are a callsign,
  //: which is a flight and not an airframe, and a registration the feed often
  //: guesses — neither is safe to look a photograph up by.
  it("does not ask without a hex", () => {
    expect(aircraftPhotoUrl(null)).toBeNull()
    expect(aircraftPhotoUrl("  ")).toBeNull()
  })
})

describe("reading the answer", () => {
  const answer = {
    photos: [
      {
        id: "abc",
        thumbnail: { src: "https://t.example/small.jpg", size: { width: 200, height: 133 } },
        thumbnail_large: {
          src: "https://t.example/large.jpg",
          size: { width: 400, height: 266 },
        },
        link: "https://www.planespotters.net/photo/abc",
        photographer: "A Photographer",
      },
    ],
  }

  it("takes the larger thumbnail and keeps the credit attached to it", () => {
    expect(parseAircraftPhoto(answer)).toEqual({
      src: "https://t.example/large.jpg",
      link: "https://www.planespotters.net/photo/abc",
      photographer: "A Photographer",
    })
  })

  it("falls back to the small thumbnail when that is all there is", () => {
    const small = { photos: [{ ...answer.photos[0], thumbnail_large: undefined }] }
    expect(parseAircraftPhoto(small)?.src).toBe("https://t.example/small.jpg")
  })

  //: A photograph with nobody named must not be shown: the licence this comes
  //: under is attribution, and an image we cannot credit is one we cannot use.
  it("refuses a photo with no photographer", () => {
    const uncredited = { photos: [{ ...answer.photos[0], photographer: "" }] }
    expect(parseAircraftPhoto(uncredited)).toBeNull()
  })

  it("says nothing rather than guessing when the shape is wrong or empty", () => {
    expect(parseAircraftPhoto({ photos: [] })).toBeNull()
    expect(parseAircraftPhoto({})).toBeNull()
    expect(parseAircraftPhoto(null)).toBeNull()
    expect(parseAircraftPhoto({ photos: [{ link: "x", photographer: "y" }] })).toBeNull()
  })
})
