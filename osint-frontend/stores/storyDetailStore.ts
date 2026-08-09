import { create } from "zustand"

/** The story pop-out card (#448).
 *
 *  Clicking a story anywhere (the situation list, the briefing blocks, a row
 *  in a map selection) opens the pop-up — page four — showing that story in
 *  full. The deck keeps every page it had.
 */
interface StoryDetailState {
  storyId: string | null
  /** Bumped on every open, so reopening the same story still moves the deck
   *  to the pop-up (#850). Identity alone cannot see a repeat. */
  opens: number
  openStory: (storyId: string) => void
  closeStory: () => void
}

export const useStoryDetailStore = create<StoryDetailState>((set) => ({
  storyId: null,
  opens: 0,
  openStory: (storyId) => set((state) => ({ storyId, opens: state.opens + 1 })),
  closeStory: () => set({ storyId: null }),
}))
