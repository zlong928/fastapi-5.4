import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Upload } from "lucide-react";
import { ChangeEvent, useRef } from "react";
import { Link } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { getBooks, uploadBook } from "@/lib/api";
import { formatChinaDate } from "@/lib/time";

export function BooksPage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const booksQuery = useQuery({ queryKey: ["books"], queryFn: getBooks });
  const uploadMutation = useMutation({
    mutationFn: uploadBook,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      if (inputRef.current) inputRef.current.value = "";
    }
  });

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    uploadMutation.mutate(file);
  }

  const books = booksQuery.data ?? [];

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Library</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Books</h1>
          <p className="mt-2 text-sm text-slate-500">Upload EPUB books and continue from your last reading position.</p>
        </div>
        <div>
          <Input ref={inputRef} type="file" accept=".epub,application/epub+zip" className="hidden" onChange={onFileChange} />
          <Button type="button" className="gap-2" disabled={uploadMutation.isPending} onClick={() => inputRef.current?.click()}>
            <Upload className="h-4 w-4" />
            {uploadMutation.isPending ? "Uploading..." : "上传 EPUB"}
          </Button>
        </div>
      </section>

      {uploadMutation.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{uploadMutation.error.message}</AlertDescription>
        </Alert>
      ) : null}
      {booksQuery.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{booksQuery.error.message}</AlertDescription>
        </Alert>
      ) : null}

      {booksQuery.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(3)].map((_, index) => <Skeleton key={index} className="h-36 w-full" />)}
        </div>
      ) : books.length ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {books.map((book) => (
            <Card key={book.id} className="transition hover:border-blue-200 hover:shadow-md">
              <CardHeader className="pb-3">
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-md bg-blue-50 text-blue-700">
                  <BookOpen className="h-5 w-5" />
                </div>
                <CardTitle className="line-clamp-2 text-lg leading-snug">{book.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="line-clamp-1 text-sm text-slate-500">{book.original_filename}</p>
                <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                  <span>{book.last_opened_at ? `Last opened ${formatChinaDate(book.last_opened_at)}` : `Added ${formatChinaDate(book.created_at)}`}</span>
                  <Button asChild size="sm">
                    <Link to={`/books/${book.id}/reader`}>Open</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-10 text-center">
          <BookOpen className="mx-auto h-8 w-8 text-slate-400" />
          <p className="mt-3 font-medium text-slate-700">No EPUB books yet</p>
          <p className="mt-1 text-sm text-slate-500">Upload an EPUB to start reading.</p>
        </div>
      )}
    </div>
  );
}
