import { FilterStateProvider, SelectionStoreProvider } from '@/components/dashboard';
import { SketchContext } from '@/hooks/sketch.context';
import { ThemeContext } from '@/hooks/theme.context';
import { useAppSketch } from '@/hooks/use-sketch';
import { useAppTheme } from '@/hooks/use-theme';
import { ServiceDeskConsole } from '@/servicedesk/ServiceDeskConsole';

// Service desk console root. The providers make the theme/sketch toggles and the
// selection + filter state live for every tile.
function App() {
  const theme = useAppTheme();
  const sketch = useAppSketch();

  return (
    <ThemeContext.Provider value={theme}>
      <SketchContext.Provider value={sketch}>
        <SelectionStoreProvider>
          <FilterStateProvider>
            <ServiceDeskConsole />
          </FilterStateProvider>
        </SelectionStoreProvider>
      </SketchContext.Provider>
    </ThemeContext.Provider>
  );
}

export default App;
