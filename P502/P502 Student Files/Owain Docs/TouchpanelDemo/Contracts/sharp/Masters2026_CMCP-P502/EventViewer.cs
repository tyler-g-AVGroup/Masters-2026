using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using CMCPP502;

namespace Masters2026
{
    /// <summary>
    /// Takes UI events from Crestron Construct and creates an easy way to view the contents.
    /// </summary>
    internal static class EventViewer
    {
        /// <summary>
        /// The maximum number of events to be contained in the <see cref="Events"/> list.
        /// </summary>
        private const int MaxEvents = 20;

        /// <summary>
        /// Backing field for the <see cref="Events"/> property.
        /// </summary>
        private static readonly List<EventItem> EventsValue = [];

        /// <summary>
        /// Occurs when the list of UI events is updated.
        /// </summary>
        public static event EventHandler<EventViewerEventArgs> EventsChanged;

        /// <summary>
        /// Gets a collection of UI events.
        /// </summary>
        public static ReadOnlyCollection<EventItem> Events { get; } = new ReadOnlyCollection<EventItem>(EventsValue);

        /// <summary>
        /// Adds a UI event to the viewer.
        /// </summary>
        /// <param name="name">The name of the contract which triggered the event.</param>
        /// <param name="eventArgs">The <see cref="UIEventArgs"/> contained in the event.</param>
        public static void AddEventToViewer(string name, UIEventArgs eventArgs)
        {
            EventsValue.Insert(0, new EventItem(name, string.Format("Sig: {0}\n", eventArgs.SigArgs.Sig.ToString())));
            TrimEvents();
            RaiseEventsChanged();
        }

        /// <summary>
        /// Adds a UI event to the viewer.
        /// </summary>
        /// <param name="name">The name of the contract which triggered the event.</param>
        /// <param name="eventArgs">The <see cref="IndexedButtonEventArgs"/> contained in the event.</param>
        public static void AddEventToViewer(string name, IndexedButtonEventArgs eventArgs)
        {
            EventsValue.Insert(0, new EventItem(name, string.Format("{0}\rSig: {1}\n", eventArgs.ToString(), eventArgs.SigArgs.Sig.ToString())));
            TrimEvents();
            RaiseEventsChanged();
        }

        /// <summary>
        /// Adds a UI event to the viewer.
        /// </summary>
        /// <param name="name">The name of the contract which triggered the event.</param>
        /// <param name="eventArgs">The <see cref="ItemEventArgs"/> contained in the event.</param>
        public static void AddEventToViewer(string name, ItemEventArgs eventArgs)
        {
            EventsValue.Insert(0, new EventItem(name, string.Format("{0}\nSig: {1}\n", eventArgs.ToString(), eventArgs.SigArgs.Sig.ToString())));
            TrimEvents();
            RaiseEventsChanged();
        }

        /// <summary>
        /// Adds a UI event to the viewer.
        /// </summary>
        /// <param name="name">The name of the contract which triggered the event.</param>
        /// <param name="eventArgs">The <see cref="DpadEventArgs"/> contained in the event.</param>
        public static void AddEventToViewer(string name, DpadEventArgs eventArgs)
        {
            EventsValue.Insert(0, new EventItem(name, string.Format("DpadEventArgs: {0}\n{1}\nSig: {2}\n", eventArgs.DpadButton.ToString(), eventArgs.ToString(), eventArgs.SigArgs.Sig.ToString())));
            TrimEvents();
            RaiseEventsChanged();
        }

        /// <summary>
        /// Adds a UI event to the viewer.
        /// </summary>
        /// <param name="name">The name of the contract which triggered the event.</param>
        /// <param name="eventArgs">The <see cref="KeypadEventArgs"/> contained in the event.</param>
        public static void AddEventToViewer(string name, KeypadEventArgs eventArgs)
        {
            EventsValue.Insert(0, new EventItem(name, string.Format("KeypadEventArgs: {0}\n{1}\nSig: {2}\n", eventArgs.KeypadButton.ToString(), eventArgs.ToString(), eventArgs.SigArgs.Sig.ToString())));
            TrimEvents();
            RaiseEventsChanged();
        }

        /// <summary>
        /// Clears the events in the <see cref="Events"/> list.
        /// </summary>
        public static void ClearEvents()
        {
            EventsValue.Clear();
            RaiseEventsChanged();
        }

        /// <summary>
        /// Invokes the <see cref="EventsChanged"/> event.
        /// </summary>
        private static void RaiseEventsChanged()
        {
            Task.Run(() =>
            {
                EventsChanged?.Invoke(typeof(EventViewer), new EventViewerEventArgs(EventsValue));
            });
        }

        /// <summary>
        /// Trims the EventsValue collection so that it does not exceed <see cref="MaxEvents"/>.
        /// </summary>
        private static void TrimEvents()
        {
            if (EventsValue.Count > MaxEvents)
            {
                EventsValue.RemoveRange(MaxEvents, EventsValue.Count - MaxEvents);
            }
        }
    }
}
