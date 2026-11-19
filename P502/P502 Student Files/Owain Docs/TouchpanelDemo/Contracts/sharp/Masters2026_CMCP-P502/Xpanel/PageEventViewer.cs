using System.Collections.ObjectModel;
using CMCPP502;

namespace Masters2026.Xpanel
{
    /// <summary>
    /// Implements the event viewer contracts.
    /// </summary>
    internal class PageEventViewer
    {
        /// <summary>
        /// The contracts to be implemented within the page.
        /// </summary>
        private readonly Contract contract;

        /// <summary>
        /// Indicates whether the event viewer subpage is open.
        /// </summary>
        private bool eventViewIsOpen;

        /// <summary>
        /// Initializes a new instance of the <see cref="PageEventViewer"/> class.
        /// </summary>
        /// <param name="contract">The contracts to implement with this control page.</param>
        internal PageEventViewer(Contract contract)
        {
            this.contract = contract;
            this.contract.Page01.EventViewerButton.EventViewerButton_Visibility_fb(true);
            EventViewer.EventsChanged += this.HandleEventViewerEventsChanged;
            this.contract.EventViewer.Clear_PressEvent += (s, e) => EventViewer.ClearEvents();
            this.contract.EventViewerButton.EventViewerOpen_PressEvent += (s, e) =>
            {
                this.eventViewIsOpen = true;
                this.UpdateEventList(EventViewer.Events);
                this.contract.Page01.EventViewerButton.EventViewerButton_Visibility_fb(false);
                this.contract.Page01.EventViewerList.EventViewerList_Visibility_fb(true);
                this.contract.Page02.EventViewerButton.EventViewerButton_Visibility_fb(false);
                this.contract.Page02.EventViewerList.EventViewerList_Visibility_fb(true);
                this.contract.Page03.EventViewerButton.EventViewerButton_Visibility_fb(false);
                this.contract.Page03.EventViewerList.EventViewerList_Visibility_fb(true);
                this.contract.Page04.EventViewerButton.EventViewerButton_Visibility_fb(false);
                this.contract.Page04.EventViewerList.EventViewerList_Visibility_fb(true);
                this.contract.Page05.EventViewerButton.EventViewerButton_Visibility_fb(false);
                this.contract.Page05.EventViewerList.EventViewerList_Visibility_fb(true);
                this.contract.Page06.EventViewerButton.EventViewerButton_Visibility_fb(false);
                this.contract.Page06.EventViewerList.EventViewerList_Visibility_fb(true);
                this.contract.Page07.EventViewerButton.EventViewerButton_Visibility_fb(false);
                this.contract.Page07.EventViewerList.EventViewerList_Visibility_fb(true);
            }
            ;
            this.contract.EventViewer.EventViewerClose_PressEvent += (s, e) =>
            {
                this.eventViewIsOpen = false;
                this.contract.Page01.EventViewerButton.EventViewerButton_Visibility_fb(true);
                this.contract.Page01.EventViewerList.EventViewerList_Visibility_fb(false);
                this.contract.Page02.EventViewerButton.EventViewerButton_Visibility_fb(true);
                this.contract.Page02.EventViewerList.EventViewerList_Visibility_fb(false);
                this.contract.Page03.EventViewerButton.EventViewerButton_Visibility_fb(true);
                this.contract.Page03.EventViewerList.EventViewerList_Visibility_fb(false);
                this.contract.Page04.EventViewerButton.EventViewerButton_Visibility_fb(true);
                this.contract.Page04.EventViewerList.EventViewerList_Visibility_fb(false);
                this.contract.Page05.EventViewerButton.EventViewerButton_Visibility_fb(true);
                this.contract.Page05.EventViewerList.EventViewerList_Visibility_fb(false);
                this.contract.Page06.EventViewerButton.EventViewerButton_Visibility_fb(true);
                this.contract.Page06.EventViewerList.EventViewerList_Visibility_fb(false);
                this.contract.Page07.EventViewerButton.EventViewerButton_Visibility_fb(true);
                this.contract.Page07.EventViewerList.EventViewerList_Visibility_fb(false);
            };
        }

        /// <summary>
        /// Event handler for when the event viewer list is updated.
        /// </summary>
        /// <param name="sender">Where the event originated.</param>
        /// <param name="e">A <see cref="EventViewerEventArgs"/>.</param>
        private void HandleEventViewerEventsChanged(object sender, EventViewerEventArgs e)
        {
            if (this.eventViewIsOpen)
            {
                this.UpdateEventList(e.Events);
            }
        }

        /// <summary>
        /// Updates the events in the this.
        /// </summary>
        /// <param name="events">The events to display in the list.</param>
        private void UpdateEventList(ReadOnlyCollection<EventItem> events)
        {
            this.contract.EventViewer.EventList.EventList_List_Visible(events.Count > 0);
            this.contract.EventViewer.EventList.EventList_Set_Number_Of_Items((ushort)events.Count);

            ushort index = 0;
            foreach (EventItem item in events)
            {
                this.contract.EventViewer.EventList.TimeStamp_Indirect(index, item.TimeStamp.ToString("HH:mm:ss.fff"));
                this.contract.EventViewer.EventList.Name_Indirect(index, item.Name);
                this.contract.EventViewer.EventList.Details_Indirect(index, item.Details);
                index++;
            }
        }
    }
}
