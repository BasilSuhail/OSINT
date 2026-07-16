import { create } from "zustand"

/** The story pop-out card (#448).
 *
 *  Clicking a story anywhere on the deck (situation list, briefing blocks)
 *  opens a second card to the LEFT of the deck — same width; the map keeps the
 *  rest. The deck stays the main card; this one shows a single story in full.
 */
interface StoryDetailState {
  storyId: string | null
  openStory: (storyId: string) => void
  closeStory: () => void
}

export const useStoryDetailStore = create<StoryDetailState>((set) => ({
  storyId: null,
  openStory: (storyId) => set({ storyId }),
  closeStory: () => set({ storyId: null }),
}))
